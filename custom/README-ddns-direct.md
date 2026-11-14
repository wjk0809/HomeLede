# DDNS-GO 探测域名 / PassWall2 默认直连

## 源码归属与交付

- 唯一 hostname 清单：`custom/data/ddns-go-probe-domains.txt`。不联网生成，升级 DDNS-GO 后应对照其 UI 默认探测 URL 审核此清单。
- `apply-feed-customizations.sh` 调用 `apply-passwall2-ddns-direct.sh`，重放到第三方 feed 的 `0_default_config`。独立执行：`sh custom/apply-passwall2-ddns-direct.sh [--check]`。检查模式不写文件；未应用或布局漂移返回非零。
- 只追加 DirectFront 的 `full:` 精确域名并显式设置 `rulenode.DirectFront=_direct`，保留 `domain:ip233.cn`、其他域名、其他规则及默认代理节点。上游 active node、group、规则顺序或限制条件改变时拒绝修改。
- base-files 的 `install-ddns-direct` 宏将同一清单和 `custom/lib/passwall2-ddns-direct.sh` 安装到 `/usr/share/homelede/`；两个输入同时纳入 `PKG_FILE_DEPENDS`。
- 独立的 `95-homelede-ddns-direct` uci-defaults 入口只运行一次迁移。成功/有意跳过返回 0，由标准 uci-defaults 生命周期删除入口；真实错误非零供后续启动重试。不会重启 PassWall2。

## 保留配置升级边界

只接管 active global node 仍为 `rulenode`、其协议为 `_shunt`、节点和已有 DirectFront 均属于 CN、DirectFront 仍为首个 shunt rule 的默认布局。动作缺失时补 `_direct`，已有 `_direct` 保持，域名仅追加缺少的精确项。

以下情况有说明地跳过，不创建或重排任何 section：未安装/配置 PassWall2、缺少 rulenode/DirectFront、非默认 active node、非 shunt、group 不匹配、显式代理/`_default`/`_blackhole` 出口、无 remarks、自定义规则顺序、限制 source/sourcePort/port/inbound/protocol/network、invert、native UCI list 域名字段、有待提交的 UCI edits。缺少 domain_list 字段但布局仍受支持时，可以补字段。

用户已有 `domain:ident.me` 不删除；另行补 `full:v6.ident.me`。因此保留配置用户的较宽匹配属于用户设置，而不是新默认。95 入口早于上游 `luci-app-passwall2` 创建空配置：新装时迁移可跳过，之后上游复制的是已重放的完整默认文件。

## 隔离验收

Linux/VM 中运行；不向传入的上游树写文件：

```sh
UCI=/path/to/real-uci LUA=/path/to/target-lua \
  TEST_SHELL=/path/to/target-ash TEST_ARTIFACTS=/outside/tree/artifacts \
  python3 custom/tests/passwall2-ddns-direct.py /path/to/HomeLede-with-feeds
```

UCI/Lua 可用 staging root 的 musl loader 包装：

```sh
RX=/path/to/staging_dir/target-x86_64_musl/root-x86
# uci wrapper:
exec "$RX/lib/ld-musl-x86_64.so.1" --library-path "$RX/lib:$RX/usr/lib" "$RX/sbin/uci" "$@"
# Lua wrapper 还需设置 LUA_PATH/LUA_CPATH 到 "$RX/usr/lib/lua"。
# ash wrapper 使用同一 loader，运行 "$RX/bin/busybox" ash "$@"。
```

测试覆盖真实 UCI 的新装/升级、幂等和保留性、非法清单与上游漂移拒绝、定制出口等 skip 边界；实际执行 base-files 安装宏和完整 feed customization 入口（仅临时复制输入）。Lua harness 加载**未修改**的上游 Xray/Sing-Box generator 和原 API，重定向真实 UCI cursor/cache，固定组件版本边界，拒绝 subprocess 副作用。分别保存 baseline/fresh/upgrade JSON。baseline 在域名已存在但映射缺失时也不产生对应规则，防止误把 group membership 当作直连动作。

这证明配置与生成映射，不等同于固件编译、刷机、实际 DDNS 请求或生产路由器服务验收。
