import { GracefulShutdown } from './graceful-shutdown';
import { RequestQueue, RandomnessJob } from '../queue/request-queue';
import { MemoryLedgerCheckpointStore } from '../listener/ledger-checkpoint';

// ─── helpers ────────────────────────────────────────────────────────────────

function makeJob(id: bigint): RandomnessJob {
  return { requestId: id, raffleContract: `CRAFFLE${id}`, timestamp: 0n };
}

/** Builds a GracefulShutdown wired to controllable fakes. */
function makeShutdown({
  jobs = [] as RandomnessJob[],
  checkpointLedger,
  processJob,
  drainTimeoutMs = 10_000,
  exitFn = jest.fn(),
}: {
  jobs?: RandomnessJob[];
  checkpointLedger?: number;
  processJob?: (job: RandomnessJob) => Promise<boolean>;
  drainTimeoutMs?: number;
  exitFn?: jest.Mock;
}) {
  const queue = new RequestQueue();
  for (const j of jobs) {
    queue.enqueue(j);
  }

  const checkpoint = new MemoryLedgerCheckpointStore();
  if (checkpointLedger !== undefined) {
    void checkpoint.save(checkpointLedger);
  }

  const stopListening = jest.fn();

  const sd = new GracefulShutdown(queue, checkpoint, {
    drainTimeoutMs,
    processJob,
    exitFn,
  });

  return { sd, queue, checkpoint, stopListening, exitFn };
}

// ─── baseline ───────────────────────────────────────────────────────────────

describe('GracefulShutdown – clean shutdown with no jobs', () => {
  it('calls stopListening, exits 0, and persists the checkpoint', async () => {
    const { sd, checkpoint, stopListening, exitFn } = makeShutdown({
      checkpointLedger: 42,
    });
    sd.register(stopListening);
    await sd.shutdown();

    expect(stopListening).toHaveBeenCalledTimes(1);
    expect(exitFn).toHaveBeenCalledWith(0);
    expect(await checkpoint.load()).toBe(42);
  });

  it('exits 0 even when there is no saved checkpoint', async () => {
    const { sd, stopListening, exitFn } = makeShutdown({});
    sd.register(stopListening);
    await sd.shutdown();

    expect(exitFn).toHaveBeenCalledWith(0);
  });
});

// ─── drain behaviour ─────────────────────────────────────────────────────────

describe('GracefulShutdown – drains in-flight jobs', () => {
  it('processes every queued job before exiting', async () => {
    const processed: bigint[] = [];
    const { sd, stopListening, exitFn } = makeShutdown({
      jobs: [makeJob(1n), makeJob(2n), makeJob(3n)],
      checkpointLedger: 100,
      processJob: async (job) => {
        processed.push(job.requestId);
        return true;
      },
    });
    sd.register(stopListening);
    await sd.shutdown();

    expect(processed).toEqual([1n, 2n, 3n]);
    expect(exitFn).toHaveBeenCalledWith(0);
  });

  it('signal mid-processing: checkpoint reflects completed work only', async () => {
    // Simulate: two jobs queued, signal arrives after job-1 completes,
    // job-2 processJob returns false (deduped / already delivered).
    const completed: bigint[] = [];
    const { sd, checkpoint, stopListening, exitFn } = makeShutdown({
      jobs: [makeJob(10n), makeJob(20n)],
      checkpointLedger: 200,
      processJob: async (_job) => {
        if (_job.requestId === 10n) {
          completed.push(_job.requestId);
          return true; // completed
        }
        // job 20 was already processed (dedup)
        return false;
      },
    });

    sd.register(stopListening);
    await sd.shutdown();

    // job 10 was processed, job 20 was skipped
    expect(completed).toEqual([10n]);
    // checkpoint is persisted (at the same ledger — no new ledger from drain)
    expect(await checkpoint.load()).toBe(200);
    expect(exitFn).toHaveBeenCalledWith(0);
  });

  it('continues draining remaining jobs when one throws', async () => {
    const completed: bigint[] = [];
    const { sd, stopListening, exitFn } = makeShutdown({
      jobs: [makeJob(1n), makeJob(2n), makeJob(3n)],
      checkpointLedger: 50,
      processJob: async (_job) => {
        if (_job.requestId === 2n) {
          throw new Error('simulated RPC failure');
        }
        completed.push(_job.requestId);
        return true;
      },
    });
    sd.register(stopListening);
    await sd.shutdown();

    // jobs 1 and 3 complete; job 2 failed but drain continued
    expect(completed).toEqual([1n, 3n]);
    expect(exitFn).toHaveBeenCalledWith(0);
  });

  it('leaves the queue empty after drain', async () => {
    const { sd, queue, stopListening } = makeShutdown({
      jobs: [makeJob(5n), makeJob(6n)],
    });
    sd.register(stopListening);
    await sd.shutdown();

    expect(queue.size()).toBe(0);
  });
});

// ─── timeout / force-exit ─────────────────────────────────────────────────

describe('GracefulShutdown – force-exits on drain timeout', () => {
  it('calls exitFn(1) when the drain exceeds drainTimeoutMs', async () => {
    const exitFn = jest.fn();

    // Manually controllable timer — avoids polluting the global setTimeout
    // with jest.useFakeTimers() and leaking into subsequent describe blocks.
    let timerCallback: (() => void) | undefined;
    const fakeSetTimeout = (fn: () => void) => {
      timerCallback = fn;
      return 0 as unknown as ReturnType<typeof setTimeout>;
    };
    const fakeClearTimeout = () => {
      timerCallback = undefined;
    };

    // processJob never resolves — simulates a hung in-flight submission.
    const neverResolves = () => new Promise<boolean>(() => {});

    const queue = new RequestQueue();
    queue.enqueue(makeJob(99n));

    const checkpoint = new MemoryLedgerCheckpointStore();
    await checkpoint.save(300);

    const stopListening = jest.fn();
    const sd = new GracefulShutdown(queue, checkpoint, {
      drainTimeoutMs: 5_000,
      processJob: neverResolves,
      exitFn,
      setTimeoutFn: fakeSetTimeout,
      clearTimeoutFn: fakeClearTimeout,
    });
    sd.register(stopListening);

    // Start shutdown without awaiting — it hangs on the processJob.
    void sd.shutdown();

    // Flush microtasks so shutdown() has reached the drainQueue await.
    await Promise.resolve();

    // Manually fire the timeout as if 5 001 ms had elapsed.
    expect(timerCallback).toBeDefined();
    timerCallback?.();

    // Flush microtasks so exitFn is called.
    await Promise.resolve();

    expect(exitFn).toHaveBeenCalledWith(1);
  });
});

// ─── double-signal guard ──────────────────────────────────────────────────

describe('GracefulShutdown – idempotent signal handling', () => {
  it('only shuts down once even if both SIGTERM and SIGINT fire', async () => {
    const exitFn = jest.fn();
    const { sd, stopListening } = makeShutdown({ exitFn, checkpointLedger: 1 });
    sd.register(stopListening);

    // Call shutdown twice (simulates rapid signal delivery).
    await Promise.all([sd.shutdown(), sd.shutdown()]);

    // stopListening and exitFn must each be called exactly once.
    expect(stopListening).toHaveBeenCalledTimes(1);
    expect(exitFn).toHaveBeenCalledTimes(1);
  });
});
