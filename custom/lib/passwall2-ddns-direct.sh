#!/bin/sh
# One-time conservative upgrade of the stock active rulenode. No service restart.
set -eu
UCI=${UCI:-uci}
CONFIG_DIR=${HOMELEDE_UCI_CONFIG_DIR:-/etc/config}
SAVEDIR=${HOMELEDE_UCI_SAVEDIR:-/tmp/.uci}
DOMAINS=${HOMELEDE_DDNS_DOMAINS:-/usr/share/homelede/ddns-go-probe-domains.txt}
u() { "$UCI" -q -c "$CONFIG_DIR" -t "$SAVEDIR" "$@"; }
get() { u get "passwall2.$1" 2>/dev/null || :; }
skip() { echo "HomeLede DDNS-GO: skip ($*)"; exit 0; }
[ -f "$CONFIG_DIR/passwall2" ] || skip 'PassWall2 not installed/configured'
u export passwall2 >/dev/null || { echo 'HomeLede DDNS-GO: unreadable/invalid UCI config' >&2; exit 1; }
[ "$(get '@global[0].node')" = rulenode ] || skip 'custom/non-stock active node'
[ "$(get rulenode)" = nodes ] && [ "$(get rulenode.protocol)" = _shunt ] || skip 'missing/non-shunt rulenode'
[ "$(get rulenode.shunt_group)" = CN ] || skip 'custom shunt group'
[ "$(get DirectFront)" = shunt_rules ] && [ "$(get DirectFront.group)" = CN ] || skip 'missing/custom DirectFront group'
[ -n "$(get DirectFront.remarks)" ] || skip 'DirectFront has no remarks'
action=$(get rulenode.DirectFront)
case "$action" in ''|_direct) ;; *) skip 'explicit non-direct DirectFront exit';; esac
[ -z "$(u changes passwall2)" ] || skip 'pending UCI edits'
first_rule=$(u show passwall2 | awk -F= '$2 == "shunt_rules" { print $1; exit }')
[ "$first_rule" = passwall2.DirectFront ] || skip 'custom shunt rule ordering'
# UCI native list is not the multiline scalar consumed by these generators.
if u export passwall2 | awk '
    /^config / { direct=($2 == "shunt_rules" && $3 == "\047DirectFront\047") }
    direct && /^[ \t]*list domain_list / { found=1 }
    END { exit !found }
'; then skip 'native list DirectFront domains'; fi
for key in source sourcePort port inbound protocol; do
    [ -z "$(get "DirectFront.$key")" ] || skip "restricted DirectFront $key"
done
case "$(get DirectFront.network)" in ''|tcp,udp) ;; *) skip 'restricted DirectFront network';; esac
[ "$(get DirectFront.invert)" != 1 ] || skip 'inverted DirectFront'
# Validate the complete installed list before any UCI writes. Hostnames only;
# do not accept URLs, suffix rules, blank lines, duplicates or normalization.
LC_ALL=C awk '
    { n++; if (length($0) > 253 || $0 !~ /^[a-z0-9.-]+$/ || seen[$0]++) bad=1
      k=split($0,a,"."); if (k < 2) bad=1
      for (i=1;i<=k;i++) if (length(a[i])<1 || length(a[i])>63 || a[i] ~ /^-/ || a[i] ~ /-$/) bad=1 }
    END { if (!n || bad) exit 1 }
' "$DOMAINS" || { echo 'HomeLede DDNS-GO: invalid hostname list' >&2; exit 1; }
old=$(get DirectFront.domain_list)
new=$old
while IFS= read -r host || [ -n "$host" ]; do
    rule="full:$host"
    if ! printf '%s\n' "$new" | grep -Fqx "$rule"; then
        if [ -n "$new" ]; then new="$new
$rule"; else new=$rule; fi
    fi
done < "$DOMAINS"
if [ "$new" != "$old" ] || [ "$action" != _direct ]; then
    u set "passwall2.DirectFront.domain_list=$new"
    u set 'passwall2.rulenode.DirectFront=_direct'
    u commit passwall2
    echo 'HomeLede DDNS-GO: DirectFront exact probe rules installed (no restart)'
else
    echo 'HomeLede DDNS-GO: already current'
fi
