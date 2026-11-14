-- Run the unmodified feed generators with real target UCI/jsonc modules.
-- Only environment boundaries (config cursor, component versions and cache
-- paths) are redirected. No generator or domain conversion is reimplemented.
local feed, config, delta, cache, backend = unpack(arg)
arg = {}
local real_uci = require 'uci'
package.loaded['luci.model.uci'] = { cursor = function() return real_uci.cursor(config, delta) end }
package.preload['luci.passwall2.com'] = function() return dofile(feed .. '/com.lua') end
package.preload['luci.passwall2.api'] = function() return dofile(feed .. '/api.lua') end
local api = require 'luci.passwall2.api'
api.CACHE_PATH = cache
api.TMP_PATH = cache
api.TMP_IFACE_PATH = cache
api.get_app_version = function(name) return name == 'sing-box' and '1.14.0' or '26.9.9' end
-- Fail loudly rather than allowing any subprocess/service/network side effect.
api.sys.call = function(command) error('unexpected system call: ' .. command) end
api.sys.exec = function(command) error('unexpected system exec: ' .. command) end
local generator = dofile(feed .. '/util_' .. backend .. '.lua')
print(_G.gen_config({flag='ddns-test', node='rulenode', no_run=true,
    local_socks_port='1080', direct_dns_query_strategy='UseIP'}))
