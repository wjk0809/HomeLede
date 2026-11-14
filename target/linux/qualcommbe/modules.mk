# SPDX-License-Identifier: GPL-2.0-only

# qcom-ppe and pcs-qcom-ipq9574 are defined in the common
# package/kernel/linux/modules/netdevices.mk. The kernel package Makefile
# includes both files during DUMP, so do not register these packages twice.
