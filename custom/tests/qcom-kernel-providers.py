#!/usr/bin/env python3
"""Guard the kernel DUMP include graph against duplicate Qualcomm providers."""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
# package/kernel/linux/Makefile includes common modules first, then EVERY
# target modules.mk even when that target is not the active build target.
paths = sorted((root / 'package/kernel/linux/modules').glob('*.mk'))
paths += sorted((root / 'target/linux').glob('*/modules.mk'))
paths += sorted((root / 'target/linux/feeds').glob('*/modules.mk'))
for name in ('qcom-ppe', 'pcs-qcom-ipq9574'):
    providers = []
    for path in paths:
        text = path.read_text()
        providers += [(path, match.group(1)) for match in re.finditer(
            rf'^define KernelPackage/{re.escape(name)}\n(.*?)^endef$', text, re.M | re.S)]
    assert len(providers) == 1, f'{name}: expected one provider, got {[str(p) for p, _ in providers]}'
    path, body = providers[0]
    assert path == root / 'package/kernel/linux/modules/netdevices.mk', path
    assert '@TARGET_qualcommbe' in body
    if name == 'qcom-ppe':
        for dependency in ('+kmod-libphy', '+kmod-pcs-qcom-ipq9574', '+kmod-nft-offload'):
            assert dependency in body, dependency
        assert 'CONFIG_NET_CLS_ACT=y' in body
    else:
        assert '+kmod-phylink' in body
    print(f'PASS: unique {name} provider and preserved dependencies')
