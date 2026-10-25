# Steam Fcitx5 Workaround

用于 Linux 原生 Steam 客户端的用户级输入法兼容方案。针对好友聊天、商店搜索等位置快速输入中文时，偶发卡顿、漏出拼音字母的情况。

本项目在 **CachyOS / Niri / Wayland + Fcitx5 Rime + Steam Runtime 3c** 的一台机器上测试：用户在临时重启 Steam 后反馈输入恢复正常，随后保留了该启动方式。这是本地兼容方案，**不是 Valve 或 Fcitx 官方发布的修复，也不保证适用于所有机器**。

## 它做了什么

Steam 自带的运行环境在测试机器上没有 Fcitx5 GTK3 模块。直接加载宿主机模块又遇到旧 GLib 缺少符号、模块版本检查不匹配的问题。

本项目：

1. 从仓库内的 Fcitx5 GTK **5.1.7** 官方源码子集构建 GTK3 输入模块及 GClient。
2. 使用 GLib 2.66 API 选择和两个小补丁，适配测试机器上的 Steam 运行环境。
3. 通过私有运行时转发入口，只在启动 `steamwebhelper_sniper_wrap.sh` 时设置：
   ```text
   GTK_IM_MODULE=fcitx
   GTK_IM_MODULE_FILE=<私有安装目录>/immodules.cache
   FCITX_ENABLE_SYNC_MODE=1
   ```
4. 创建用户级 `steam.desktop`，让应用菜单通过该入口启动 Steam。

同步选项要求命中该 GTK 模块的按键调用等待 Fcitx5 返回处理结果。**实测中 Steam 仍创建了 XIM 连接，因此不能把本方案描述成“所有聊天输入都切换到了 D-Bus”。**用户反馈是改善现象的证据，尚不是对完整根因的证明。

脚本不更换输入法引擎，不修改词库，不修改系统库和 Steam 安装目录中的程序文件，也不设置全局输入法环境变量。其他运行时命令由转发入口原样执行；只有上述网页/聊天启动命令得到输入覆盖参数。

## 支持范围

已验证的组合：

| 项目 | 测试版本 |
| --- | --- |
| 系统 / 会话 | CachyOS，Niri 26.04，Wayland |
| Fcitx5 | 5.1.23 |
| fcitx5-gtk 源码 | 5.1.7 |
| Rime / librime | fcitx5-rime 5.1.16 / librime 1.17.0 |
| Steam 客户端构建 | 1792618285 |
| Steam 运行环境 | Steam Runtime 3c，3c.0.20260824.257593 |
| CPU 架构 | x86-64 |

目前针对 **原生安装的 Steam + Steam Runtime 3c**。没有验证 Flatpak、Snap、其他 CPU 架构或其他 Steam 运行时布局。

前提是 Fcitx5 已运行，并且能在其他应用中正常输入中文。本项目不负责从零配置输入法。

## 安装

Arch Linux / CachyOS 的构建依赖：

```sh
sudo pacman -S --needed base-devel git python gtk3 glib2-devel libxkbcommon libx11
```

然后以普通用户运行：

```sh
git clone https://github.com/SimonQvQ/steam-fcitx5-workaround.git
cd steam-fcitx5-workaround
python3 steam_fcitx5.py install
```

源码已包含在仓库中，构建时不再下载依赖或调用包管理器。默认安装位置：

- 私有模块、模块缓存和运行时入口：`${XDG_DATA_HOME:-~/.local/share}/steam-fcitx5-workaround/`
- 应用菜单入口：`${XDG_DATA_HOME:-~/.local/share}/applications/steam.desktop`

如果已有自定义的用户级 `steam.desktop`，安装器会拒绝直接覆盖。确认要替换后，使用：

```sh
python3 steam_fcitx5.py install --replace-desktop
```

原入口会备份在私有安装目录中，卸载时恢复。重复安装不会丢掉第一次的备份。安装器拒绝覆盖已经安装后又被手动编辑的菜单入口。

Steam 不在默认位置时：

```sh
python3 steam_fcitx5.py install --steam-root /path/to/Steam
```

安装脚本**不会替你重启 Steam**。保存聊天草稿后，在 Steam 菜单里选择“退出”，再从应用菜单打开。仅关闭主窗口不足以结束后台进程。

终端中的普通 `steam` 命令仍指向发行版入口；终端测试请直接运行安装目录里的 `start-steam.sh`。

## 测试和验证

先查看运行中的 `steamwebhelper` 是否包含指定环境变量和私有模块：

```sh
python3 steam_fcitx5.py doctor
```

可选的运行时探针：

```sh
python3 steam_fcitx5.py doctor --runtime-test
```

它会通过现有 Steam 运行环境启动一个独立 GTK 探针，检查 `FcitxIMContext` 是否能注册，以及同步参数是否生效。它不重启 Steam、不向聊天框注入文字、不发送消息；Steam 运行时本身可能更新缓存。

**探针通过只代表模块可以加载，不代表真实聊天故障已经解决。**最后仍需在 Steam 客户端聊天框里快速输入几句，先不要发送，检查是否还会漏字母。无需改变输入速度来迁就测试。

测试机器同时关闭了 Fcitx5 的“在程序中显示预编辑文本”。单独关闭该选项并没有解决漏字；成功反馈发生在随后加载本项目模块并启用同步模式之后。安装器不会改这个全局选项，如果要保持同样的对照条件，请在 Fcitx5 设置中手动取消勾选。

## 卸载

```sh
python3 steam_fcitx5.py uninstall
```

它会恢复安装前的用户级菜单入口；如果原来没有该入口，则移除覆盖、恢复使用系统入口，然后删除本项目的私有安装目录。源码检出目录和 `.build/` 构建缓存保留。

如果菜单入口在安装后被手动编辑，卸载器会停止并保留文件，避免覆盖你的改动。已经运行的 Steam 需要完整退出再打开，才会停止使用已加载的模块。

使用了自定义 `--prefix` 时，安装、诊断和卸载必须传入同一个路径。

## 源码与构建

```sh
python3 steam_fcitx5.py build
python3 -m unittest discover -s tests -v
```

2026-10-25 发布前验证：独立源码构建成功，7 项自动测试通过；在含空格的临时安装路径中完成安装 → Steam Runtime 3c GTK 探针 → 卸载的完整检查，探针确认 `Fcitx type registered: yes; synchronous: 1`。现有的 Steam 菜单入口保持不变。真实聊天的改善来自用户实测反馈，不是自动测试发送消息得出的结果。

项目结构：

```text
steam_fcitx5.py             构建、安装、诊断和卸载工具
patches/glib-2.66.patch     相对于官方源码的兼容补丁
vendor/fcitx5-gtk/          官方 5.1.7 的必要源码子集及版权声明
vendor/SOURCE.json         上游版本、提交及来源
vendor/SHA256SUMS.json      检出源码的完整性检查清单
tools/context-probe.c      不输入文字的 GTK 模块探针
tests/                     入口转发、参数隔离、备份和卸载测试
```

兼容改动：

- `g_module_check_init` 使用 GLib 2.66 的最低版本检查，与构建时的 API 选择保持一致；不是取消版本检查。
- `g_memdup2` 分支依据 `GLIB_VERSION_MIN_REQUIRED` 选择，让旧环境走已有回退实现。
- GClient 使用 GLib 的通用信号 marshaller，避免额外依赖 `glib-genmarshal`。
- 模块通过 `$ORIGIN` RPATH 使用旁边的私有 GClient。

仓库不提供预编译二进制，避免把宿主机 ABI 假设带到其他系统。即使设置了 GLib 2.66 API 选择，宿主编译器、其他 GTK 依赖和 Steam 运行环境仍可能影响兼容性；请以运行时探针和客户端实测为准。

## 已知限制

- 仅有上述单机实测，无法保证每个版本或输入法引擎都有效。
- 依赖 Steam 的 `STEAM_RUNTIME_STEAMRT` 开发者覆盖入口和现有启动脚本名称。Steam 大版本更新后可能需要重新验证。
- Steam 仍可能维护 XIM 输入上下文；本项目没有证明、也不宣称完全替代 XIM。
- 没有直接修改游戏的启动参数，但自定义运行时覆盖值会存在于 Steam 的进程环境中；未验证所有游戏和覆盖层组合。
- 对关闭预编辑与同步模块两项的全部组合尚未做完整 A/B 测试。
- 无效时请先卸载，再附系统、会话、Fcitx5 / Steam 版本及 `doctor` 的相关输出。不要上传账号信息、聊天内容或完整进程环境。

## 相关资料

- [Steam 快速输入时字母漏入文本框的上游报告](https://github.com/ValveSoftware/steam-for-linux/issues/13471)
- [Fcitx5 GTK 官方源码](https://github.com/fcitx/fcitx5-gtk/tree/5.1.7)
- [Fcitx5 Wayland 配置说明](https://fcitx-im.org/wiki/Using_Fcitx_5_on_Wayland)
- [Arch Linux 中文论坛：Steam 使用中文输入法](https://forum.archlinuxcn.org/t/topic/15900/2)

## 许可证

本项目使用 **LGPL-2.1-or-later**。上游 Fcitx5 GTK 源码保留原作者版权头和许可证，详见根目录 `LICENSE`、`vendor/README.md` 及源码中的 SPDX 声明。
