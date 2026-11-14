#!/usr/bin/env python3
"""Isolated integration tests. Args: HomeLede tree containing the upstream feed.
Run on Linux with UCI pointing to a real UCI executable (target musl wrapper OK).
Never operates on that tree's configuration or feed: all writes are temporary.
"""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[2]
UPSTREAM = Path(sys.argv.pop(1)).resolve()
DEFAULT = Path('feeds/pw2luci/luci-app-passwall2/root/usr/share/passwall2/0_default_config')
HOSTS = ['ddns.oray.com', 'ip.3322.net', '4.ipw.cn', 'v4.yinghualuo.cn',
         'myip.ipip.net', 'speed.neu6.edu.cn', 'v6.ident.me', '6.ipw.cn',
         'v6.yinghualuo.cn', 'api.ipify.org', 'api64.ipify.org']

class Defaults(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='pw2-ddns-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        shutil.copytree(SOURCE / 'custom', self.root / 'custom')
        self.file = self.root / DEFAULT
        self.file.parent.mkdir(parents=True)
        shutil.copyfile(UPSTREAM / DEFAULT, self.file)
        self.config = self.root / 'config'
        self.config.mkdir()
        self.delta = self.root / 'delta'
        self.delta.mkdir()

    def apply(self, *args):
        return subprocess.run(['sh', str(self.root / 'custom/apply-passwall2-ddns-direct.sh'), *args], text=True, capture_output=True)

    def uci(self, *args):
        return subprocess.check_output([os.environ['UCI'], '-c', str(self.config), '-t', str(self.delta), *args], text=True).rstrip('\n')

    def migrate(self):
        env = dict(os.environ, HOMELEDE_DDNS_DOMAINS=str(self.root / 'custom/data/ddns-go-probe-domains.txt'),
                   HOMELEDE_UCI_CONFIG_DIR=str(self.config), HOMELEDE_UCI_SAVEDIR=str(self.delta))
        return subprocess.run([os.environ.get('TEST_SHELL', 'sh'), str(self.root / 'custom/lib/passwall2-ddns-direct.sh')],
                              env=env, text=True, capture_output=True)

    def test_preserved_upgrade_appends_without_touching_user_state(self):
        shutil.copyfile(self.file, self.config / 'passwall2')
        self.uci('set', 'passwall2.DirectFront.domain_list=domain:ip233.cn\ndomain:ident.me\nfull:my.example.com')
        self.uci('set', 'passwall2.examplenode.address=user.example.com')
        self.uci('add', 'passwall2', 'subscribe_list')
        self.uci('commit', 'passwall2')
        before = self.uci('export', 'passwall2')
        p = self.migrate()
        self.assertEqual(p.returncode, 0, p.stderr)
        lines = self.uci('get', 'passwall2.DirectFront.domain_list').splitlines()
        self.assertEqual(lines[:3], ['domain:ip233.cn', 'domain:ident.me', 'full:my.example.com'])
        self.assertEqual(lines[3:], ['full:' + x for x in HOSTS])
        self.assertEqual(self.uci('get', 'passwall2.rulenode.DirectFront'), '_direct')
        after = self.uci('export', 'passwall2')
        restored = after.replace(''.join('\nfull:' + x for x in HOSTS), '').replace("\n\toption DirectFront '_direct'", '')
        self.assertEqual(restored, before)
        self.assertEqual(self.migrate().returncode, 0)
        self.assertEqual(self.uci('export', 'passwall2'), after)
        self.assertEqual(self.uci('changes', 'passwall2'), '')

    def test_upgrade_skips_custom_missing_restricted_and_pending_state(self):
        cases = [('set', 'passwall2.rulenode.DirectFront=_blackhole'),
                 ('set', 'passwall2.rulenode.DirectFront=_default'),
                 ('set', 'passwall2.rulenode.DirectFront=examplenode'),
                 ('set', 'passwall2.rulenode.shunt_group=OTHER'),
                 ('set', 'passwall2.DirectFront.group=OTHER'),
                 ('set', 'passwall2.@global[0].node=examplenode'),
                 ('set', 'passwall2.rulenode.protocol=socks'),
                 ('delete', 'passwall2.DirectFront'), ('delete', 'passwall2.rulenode'),
                 ('set', 'passwall2.DirectFront.port=443'),
                 ('set', 'passwall2.DirectFront.invert=1'),
                 ('set', 'passwall2.DirectFront.network=tcp'),
                 ('reorder', 'passwall2.DirectFront=99'),
                 ('add_list', 'passwall2.DirectFront.domain_list=full:user.example.com')]
        for command in cases:
            with self.subTest(command=command):
                shutil.copyfile(self.file, self.config / 'passwall2')
                self.uci(*command)
                self.uci('commit', 'passwall2')
                before = (self.config / 'passwall2').read_bytes()
                p = self.migrate()
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIn('skip', p.stdout)
                self.assertEqual((self.config / 'passwall2').read_bytes(), before)
                self.assertEqual(self.uci('changes', 'passwall2'), '')
        shutil.copyfile(self.file, self.config / 'passwall2')
        self.uci('set', 'passwall2.examplenode.address=pending.example.com')
        before = self.uci('changes', 'passwall2')
        self.assertIn('skip', self.migrate().stdout)
        self.assertEqual(self.uci('changes', 'passwall2'), before)

    def test_upgrade_rejects_corrupt_config_without_writes(self):
        broken = self.file.read_bytes() + b"\nconfig nodes 'unterminated\n"
        (self.config / 'passwall2').write_bytes(broken)
        self.assertNotEqual(self.migrate().returncode, 0)
        self.assertEqual((self.config / 'passwall2').read_bytes(), broken)

    def test_upgrade_rejects_invalid_list_without_writes(self):
        shutil.copyfile(self.file, self.config / 'passwall2')
        before = (self.config / 'passwall2').read_bytes()
        listing = self.root / 'custom/data/ddns-go-probe-domains.txt'
        for invalid in ['https://ip.3322.net/', 'domain:ident.me', 'a..com', '-a.com',
                        'a_.com', 'a.com\na.com', '', 'IP.3322.net']:
            with self.subTest(invalid=invalid):
                listing.write_text(invalid + '\n')
                self.assertNotEqual(self.migrate().returncode, 0)
                self.assertEqual((self.config / 'passwall2').read_bytes(), before)
                self.assertEqual(self.uci('changes', 'passwall2'), '')

    def test_supported_upgrade_missing_domain_field_and_existing_direct(self):
        for remove_domains in (False, True):
            shutil.copyfile(self.file, self.config / 'passwall2')
            self.uci('set', 'passwall2.rulenode.DirectFront=_direct')
            if remove_domains:
                self.uci('delete', 'passwall2.DirectFront.domain_list')
            self.uci('commit', 'passwall2')
            self.assertEqual(self.migrate().returncode, 0)
            lines = self.uci('get', 'passwall2.DirectFront.domain_list').splitlines()
            self.assertTrue(set('full:' + h for h in HOSTS) <= set(lines))
            self.assertEqual(self.uci('get', 'passwall2.rulenode.DirectFront'), '_direct')

    def test_whole_feed_hook_in_isolated_copied_inputs(self):
        inputs = [
            'feeds/luci/modules/luci-mod-status/htdocs/luci-static/resources/view/status/index.js',
            'feeds/luci/modules/luci-mod-status/ucode/template/admin_status/index.ut',
            'feeds/packages/utils/cgroupfs-mount/files/cgroupfs-mount.init',
            'feeds/packages/utils/ttyd/files/ttyd.init',
            'feeds/xiaoqingfeng/luci-app-homestatus/root/usr/share/luci/menu.d/zz-homelede-overview.json']
        for name in inputs:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(UPSTREAM / name, target)
        script = self.root / 'custom/apply-feed-customizations.sh'
        for args in ([], ['--check'], []):
            p = subprocess.run(['sh', str(script), *args], text=True, capture_output=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.apply('--check').returncode, 0)

    def test_build_hook_and_base_files_install_single_source(self):
        hook = (SOURCE / 'custom/apply-feed-customizations.sh').read_text()
        self.assertIn('sh "$TOPDIR/custom/apply-passwall2-ddns-direct.sh" ${1:-} || exit 1', hook)
        make = (SOURCE / 'package/base-files/Makefile').read_text()
        self.assertIn('$(call Package/base-files/install-ddns-direct,$(1))', make)
        self.assertIn('PKG_FILE_DEPENDS+=$(TOPDIR)/custom/data/ddns-go-probe-domains.txt $(TOPDIR)/custom/lib/passwall2-ddns-direct.sh', make)
        block = re.search(r'(?ms)^define Package/base-files/install-ddns-direct\n.*?^endef', make)
        self.assertIsNotNone(block)
        stage = self.root / 'installed'
        harness = self.root / 'install.mk'
        harness.write_text('TOPDIR:=' + str(SOURCE) + '\nINSTALL_DIR:=mkdir -p\nINSTALL_DATA:=install -m644\nINSTALL_BIN:=install -m755\n' + block[0] + '\nall:\n\t$(call Package/base-files/install-ddns-direct,' + str(stage) + ')\n')
        subprocess.run(['make', '-f', str(harness)], check=True, capture_output=True)
        self.assertEqual((stage / 'usr/share/homelede/ddns-go-probe-domains.txt').read_bytes(),
                         (SOURCE / 'custom/data/ddns-go-probe-domains.txt').read_bytes())
        self.assertEqual((stage / 'usr/share/homelede/passwall2-ddns-direct.sh').read_bytes(),
                         (SOURCE / 'custom/lib/passwall2-ddns-direct.sh').read_bytes())
        boot = SOURCE / 'package/base-files/files/etc/uci-defaults/95-homelede-ddns-direct'
        self.assertIn('/usr/share/homelede/passwall2-ddns-direct.sh', boot.read_text())
        self.assertNotIn('restart', boot.read_text())
        subprocess.run(['sh', '-n', str(boot)], check=True)

    def test_real_xray_and_singbox_generators_exact_direct_mapping(self):
        feed = UPSTREAM / 'feeds/pw2luci/luci-app-passwall2/luasrc/passwall2'
        cache = self.root / 'cache'
        cache.mkdir()
        def generate(backend):
            p = subprocess.run([os.environ['LUA'], str(SOURCE / 'custom/tests/passwall2-ddns-generator.lua'),
                                str(feed), str(self.config), str(self.delta), str(cache), backend],
                               text=True, capture_output=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            if os.environ.get('TEST_ARTIFACTS'):
                artifacts = Path(os.environ['TEST_ARTIFACTS'])
                artifacts.mkdir(parents=True, exist_ok=True)
                (artifacts / (flavor + '-' + backend + '.json')).write_text(p.stdout)
            return json.loads(p.stdout)
        # Prove missing action is NOT direct: the upstream default emits no rule.
        shutil.copyfile(self.file, self.config / 'passwall2')
        flavor = 'baseline'
        self.uci('set', 'passwall2.DirectFront.domain_list=domain:ip233.cn\nfull:v6.ident.me')
        self.uci('commit', 'passwall2')
        baseline = generate('xray')
        self.assertFalse(any('full:v6.ident.me' in r.get('domains', []) for r in baseline['routing']['rules']))
        baseline = generate('sing-box')
        self.assertFalse(any('v6.ident.me' in r.get('domain', []) for r in baseline['route']['rules']))
        self.assertEqual(self.apply().returncode, 0)
        flavor = 'fresh'
        shutil.copyfile(self.file, self.config / 'passwall2')
        for backend in ['xray', 'sing-box']:
            with self.subTest(backend=backend):
                output = generate(backend)
                if backend == 'xray':
                    matches = [r for r in output['routing']['rules'] if 'full:v6.ident.me' in r.get('domains', [])]
                    self.assertEqual(len(matches), 1)
                    rule = matches[0]
                    self.assertEqual(rule['outboundTag'], 'direct')
                    self.assertTrue(set('full:' + h for h in HOSTS) <= set(rule['domains']))
                    self.assertNotIn('domain:ident.me', rule['domains'])
                    self.assertTrue(any(o['tag'] == 'direct' and o['protocol'] == 'freedom' for o in output['outbounds']))
                else:
                    matches = [r for r in output['route']['rules'] if 'v6.ident.me' in r.get('domain', [])]
                    self.assertEqual(len(matches), 1)
                    rule = matches[0]
                    self.assertEqual(rule['outbound'], 'direct')
                    self.assertTrue(set(HOSTS) <= set(rule['domain']))
                    self.assertFalse(set(HOSTS) & set(rule.get('domain_suffix', [])))
                    self.assertFalse(set(HOSTS) & set(rule.get('domain_keyword', [])))
                    self.assertTrue(any(o['tag'] == 'direct' and o['type'] == 'direct' for o in output['outbounds']))

        # Preserved upgrade uses the same actual backends; retain broad ident.me.
        shutil.copyfile(UPSTREAM / DEFAULT, self.config / 'passwall2')
        self.uci('set', 'passwall2.DirectFront.domain_list=domain:ip233.cn\ndomain:ident.me')
        self.uci('commit', 'passwall2')
        self.assertEqual(self.migrate().returncode, 0)
        flavor = 'upgrade'
        for backend in ['xray', 'sing-box']:
            output = generate(backend)
            rules = output['routing']['rules'] if backend == 'xray' else output['route']['rules']
            field = 'domains' if backend == 'xray' else 'domain'
            expected = ['full:' + h for h in HOSTS] if backend == 'xray' else HOSTS
            rule = next(r for r in rules if expected[0] in r.get(field, []))
            self.assertTrue(set(expected) <= set(rule[field]))
            self.assertEqual(rule['outboundTag' if backend == 'xray' else 'outbound'], 'direct')
            self.assertIn('domain:ident.me' if backend == 'xray' else 'ident.me',
                          rule['domains' if backend == 'xray' else 'domain_suffix'])

    def test_fail_closed_validation_and_layout_drift(self):
        original = self.file.read_bytes()
        listing = self.root / 'custom/data/ddns-go-probe-domains.txt'
        valid = listing.read_bytes()
        for invalid in ['https://ip.3322.net/', 'domain:ident.me', 'a..com',
                        '-a.com', 'a_.com', 'a.com\na.com', '', 'IP.3322.net']:
            with self.subTest(invalid=invalid):
                listing.write_text(invalid + '\n')
                self.assertNotEqual(self.apply().returncode, 0)
                self.assertEqual(self.file.read_bytes(), original)
        listing.write_bytes(valid)
        for old, new in [("option node 'rulenode'", "option node 'examplenode'"),
                         ("option network 'tcp,udp'\n\toption domain_list 'domain:ip233.cn'", "option network 'tcp'\n\toption domain_list 'domain:ip233.cn'"),
                         ("option remarks 'rulenode'", "option remarks 'rulenode'\n\tlist DirectFront '_direct'"),
                         ("option remarks 'DirectFront'", "option remarks 'DirectFront'\n\toption port '443'"),
                         ("config shunt_rules 'DirectFront'", "config shunt_rules 'Earlier'\n\toption group 'CN'\n\nconfig shunt_rules 'DirectFront'"),
                         ("option group 'CN'", "option group 'OTHER'"),
                         ("option protocol '_shunt'", "option protocol 'socks'"),
                         ("config nodes 'rulenode'", "config nodes 'custom'"),
                         ("option domain_list 'domain:ip233.cn'", "list domain_list 'domain:ip233.cn'"),
                         ("option shunt_group 'CN'", "option shunt_group 'OTHER'")]:
            with self.subTest(drift=new):
                self.file.write_bytes(original.replace(old.encode(), new.encode(), 1))
                before = self.file.read_bytes()
                self.assertNotEqual(self.apply().returncode, 0)
                self.assertEqual(self.file.read_bytes(), before)
        self.file.write_bytes(original)
        self.assertNotEqual(self.apply('--check').returncode, 0)
        self.assertEqual(self.file.read_bytes(), original)

    def test_fresh_default_has_exact_rules_and_explicit_direct(self):
        p = self.apply()
        self.assertEqual(p.returncode, 0, p.stderr)
        shutil.copyfile(self.file, self.config / 'passwall2')
        lines = self.uci('get', 'passwall2.DirectFront.domain_list').splitlines()
        self.assertIn('domain:ip233.cn', lines)
        for host in HOSTS:
            self.assertEqual(lines.count('full:' + host), 1)
        self.assertNotIn('domain:ident.me', lines)
        self.assertEqual(self.uci('get', 'passwall2.rulenode.DirectFront'), '_direct')
        self.assertEqual(self.uci('get', 'passwall2.rulenode.default_node'), 'examplenode')
        before = self.file.read_bytes()
        restored = before.decode().replace(''.join('\nfull:' + h for h in HOSTS), '').replace("\toption DirectFront '_direct'\n", '')
        self.assertEqual(restored, (UPSTREAM / DEFAULT).read_text())
        if os.environ.get('TEST_ARTIFACTS'):
            artifacts = Path(os.environ['TEST_ARTIFACTS'])
            artifacts.mkdir(parents=True, exist_ok=True)
            (artifacts / 'new-default-config').write_bytes(before)
            import difflib
            diff = difflib.unified_diff((UPSTREAM / DEFAULT).read_text().splitlines(True),
                                        self.file.read_text().splitlines(True), fromfile='upstream', tofile='customized')
            (artifacts / 'new-default.diff').write_text(''.join(diff))
        self.assertEqual(self.apply('--check').returncode, 0)
        self.assertEqual(self.apply().returncode, 0)
        self.assertEqual(self.file.read_bytes(), before)

if __name__ == '__main__':
    unittest.main(verbosity=2)
