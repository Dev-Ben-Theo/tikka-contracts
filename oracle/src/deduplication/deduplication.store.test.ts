import { DeduplicationStore } from './deduplication.store';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

describe('DeduplicationStore', () => {
  let testStorePath: string;
  let store: DeduplicationStore;

  beforeEach(() => {
    // Create a unique temporary file for each test
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dedup-test-'));
    testStorePath = path.join(tempDir, 'seen-requests.json');
    store = new DeduplicationStore(testStorePath);
  });

  afterEach(() => {
    // Cleanup
    if (fs.existsSync(testStorePath)) {
      fs.unlinkSync(testStorePath);
    }
    const tempDir = path.dirname(testStorePath);
    if (fs.existsSync(tempDir)) {
      fs.rmSync(tempDir, { recursive: true, force: true });
    }
  });

  it('first-seen accepted', () => {
    const isDup = store.isDuplicate(1n, 'addr1');
    expect(isDup).toBe(false);
  });

  it('duplicate rejected', () => {
    store.isDuplicate(1n, 'addr1');
    const isDup = store.isDuplicate(1n, 'addr1');
    expect(isDup).toBe(true);
  });

  it('distinct ids independent', () => {
    store.isDuplicate(1n, 'addr1');
    
    // Different requestId, same address
    const isDup1 = store.isDuplicate(2n, 'addr1');
    expect(isDup1).toBe(false);

    // Same requestId, different address
    const isDup2 = store.isDuplicate(1n, 'addr2');
    expect(isDup2).toBe(false);
  });

  it('restart behavior loads history from disk', () => {
    store.isDuplicate(1n, 'addr1');
    store.isDuplicate(2n, 'addr2');

    // Simulate restart by creating a new instance with the same file
    const restartedStore = new DeduplicationStore(testStorePath);
    
    // Should still reject duplicates seen before "restart"
    expect(restartedStore.isDuplicate(1n, 'addr1')).toBe(true);
    expect(restartedStore.isDuplicate(2n, 'addr2')).toBe(true);

    // Should accept new ones
    expect(restartedStore.isDuplicate(3n, 'addr1')).toBe(false);
  });

  it('behaves in-memory if disk is unavailable (e.g., bad path)', () => {
    // Create a store that cannot write to disk because the path is a directory
    const dirPath = path.dirname(testStorePath);
    const badStore = new DeduplicationStore(dirPath);

    // It should still work in-memory (disk write errors are caught and logged)
    expect(badStore.isDuplicate(1n, 'addr1')).toBe(false);
    expect(badStore.isDuplicate(1n, 'addr1')).toBe(true);
  });

  it('no eviction behavior under many entries (unbounded growth)', () => {
    const entriesToInsert = 1000;
    for (let i = 0; i < entriesToInsert; i++) {
      store.isDuplicate(BigInt(i), 'addr1');
    }

    // Verify the first entry is still remembered (no eviction)
    expect(store.isDuplicate(0n, 'addr1')).toBe(true);
    
    // Verify the last entry is remembered
    expect(store.isDuplicate(BigInt(entriesToInsert - 1), 'addr1')).toBe(true);

    // Disk file should contain all entries
    const data = JSON.parse(fs.readFileSync(testStorePath, 'utf8'));
    expect(data.seen.length).toBe(entriesToInsert);
  });
});
