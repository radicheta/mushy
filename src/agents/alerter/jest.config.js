module.exports = {
  testEnvironment: 'node',
  testMatch: ['**/test/**/*.test.js'],
  testPathIgnorePatterns: ['/node_modules/', '/fixtures/', '/helpers/'],
  verbose: true,
  testTimeout: 10000
};
