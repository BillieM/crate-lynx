const dns = require("node:dns");

const originalLookup = dns.lookup.bind(dns);
const originalPromiseLookup = dns.promises.lookup.bind(dns.promises);

function normalizeHostname(hostname) {
  return hostname === "localhost" ? "127.0.0.1" : hostname;
}

dns.lookup = function patchedLookup(hostname, options, callback) {
  return originalLookup(normalizeHostname(hostname), options, callback);
};

dns.promises.lookup = function patchedPromiseLookup(hostname, options) {
  return originalPromiseLookup(normalizeHostname(hostname), options);
};
