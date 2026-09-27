/** @type {import('jest').Config} */
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  roots: ['<rootDir>/src'],
  testMatch: ['**/*.test.ts'],
  collectCoverageFrom: [
    'src/**/*.ts',
    '!src/**/*.test.ts',
    '!src/index.ts', // entry-point bootstrap; covered by integration tests
  ],
  coverageThreshold: {
    global: {
      lines: 75,
      functions: 65,
      branches: 65,
      statements: 75,
    },
  },
};
