#!/bin/sh
# Replayed after feed updates. Own only DirectFront domains and default action.
set -eu
case "${1:-}" in ''|--check) ;; *) echo 'usage: apply-passwall2-ddns-direct.sh [--check]' >&2; exit 2;; esac
TOPDIR=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
exec python3 - "$TOPDIR" "${1:-}" <<'PY'
from pathlib import Path
import re
import sys
root = Path(sys.argv[1])
target = root / 'feeds/pw2luci/luci-app-passwall2/root/usr/share/passwall2/0_default_config'
text = target.read_text()
hosts = (root / 'custom/data/ddns-go-probe-domains.txt').read_text().splitlines()
if not hosts or len(hosts) != len(set(hosts)):
    sys.exit('[FAIL] empty or duplicate probe hostname list')
label = r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
for host in hosts:
    if len(host) > 253 or not re.fullmatch(label + r'(?:\.' + label + r')+', host):
        sys.exit('[FAIL] invalid probe hostname: ' + repr(host))
# Named section boundaries, including multiline option values. Refuse drift,
# duplicates or surprising formatting rather than rewriting unrelated defaults.
def section(kind, name):
    matches = list(re.finditer(r"(?m)^config " + kind + " '" + name + r"'[ \t]*\n", text))
    if len(matches) != 1:
        raise ValueError('missing/duplicate ' + name)
    match = matches[0]
    end = re.search(r'(?m)^config ', text[match.end():])
    stop = match.end() + end.start() if end else len(text)
    return match.start(), stop, text[match.start():stop]
def option(block, key):
    values = re.findall(r"(?m)^\toption " + key + r" '([^']*)'[ \t]*$", block)
    entries = re.findall(r'(?m)^[ \t]+(?:option|list)[ \t]+' + key + r'(?=[ \t])', block)
    if len(values) > 1 or len(entries) != len(values):
        raise ValueError('duplicate/unsupported option layout ' + key)
    return values[0] if values else None

globals_ = list(re.finditer(r'(?ms)^config global\n(.*?)(?=^config |\Z)', text))
if len(globals_) != 1 or option(globals_[0][1], 'node') != 'rulenode':
    sys.exit('[FAIL] active default shunt layout drift')
_, _, node = section('nodes', 'rulenode')
if option(node, 'protocol') != '_shunt' or option(node, 'shunt_group') != 'CN':
    sys.exit('[FAIL] default rulenode layout drift')
if option(node, 'DirectFront') not in (None, '_direct'):
    sys.exit('[FAIL] upstream DirectFront action drift')
a, b, direct = section('shunt_rules', 'DirectFront')
if (option(direct, 'group') != 'CN' or option(direct, 'domain_list') is None
        or option(direct, 'network') != 'tcp,udp' or not option(direct, 'remarks')):
    sys.exit('[FAIL] DirectFront layout drift')
first_rule = re.search(r"(?m)^config shunt_rules '([^']+)'", text)
if not first_rule or first_rule[1] != 'DirectFront':
    sys.exit('[FAIL] upstream shunt ordering drift')
if any(option(direct, key) for key in ('source', 'sourcePort', 'port', 'inbound', 'protocol')) or option(direct, 'invert') == '1':
    sys.exit('[FAIL] restricted upstream DirectFront')
match = re.search(r"(?m)^\toption domain_list '([^']*)'", direct)
if not match:
    raise ValueError('DirectFront domain_list layout drift')
lines = match[1].splitlines()
for host in hosts:
    rule = 'full:' + host
    if rule not in lines:
        lines.append(rule)
direct = direct[:match.start(1)] + '\n'.join(lines) + direct[match.end(1):]
text = text[:a] + direct + text[b:]
a, b, node = section('nodes', 'rulenode')
if "\toption DirectFront " not in node:
    node = node.rstrip('\n') + "\n\toption DirectFront '_direct'\n\n"
text = text[:a] + node + text[b:]
if text == target.read_text():
    print('[ ok ] PassWall2 DDNS-GO exact DirectFront defaults')
elif sys.argv[2] == '--check':
    sys.exit('[MISS] PassWall2 DDNS-GO defaults need applying')
else:
    target.write_text(text)
    print('[done] PassWall2 DDNS-GO exact DirectFront defaults')
PY
