# 原生中文安装器

把现有 1.1.1 汉化补丁封装为 macOS AppKit 安装向导。收件人无需终端、AI、Python、Node 或开发工具；既有补丁的版本、官方签名、资源指纹、备份和恢复检查均保留。安装器自身版本为 1.0.0，最低 macOS 13，仅 arm64。

## 收件人流程

解压 → 双击“Screen Studio 中文安装器.app” → 保存工作并退出 Screen Studio → 点击“检查并安装”。仅当应用目录没有写入权限时，请求 macOS 管理员授权。安装完成后打开 Screen Studio，自行确认系统隐私权限并测试录屏/预览/导出。

原版恢复入口会自动使用本次安装记录，无需找命令。失败会保留诊断和备份。没有安装回执时也可手动选择原先保留的 state.json，但不支持跳过其版本与签名校验。

此版本只有本机临时签名，没有 Developer ID 或 Apple 公证。互联网下载首次打开可能需要本人在“隐私与安全性”确认；企业限制或明确的恶意软件/损坏提示不能绕过。系统录屏、辅助功能及 Touch ID/密码不能替用户自动批准。因此不能宣传成每台电脑从下载到录屏只需要一次点击。

## 构建

在仓库根目录运行（仅开发者）：

```sh
python3 -m venv .build-venv
.build-venv/bin/python -m pip install -r desktop/requirements-build.txt
.build-venv/bin/python scripts/build_desktop.py
```

输出 `dist/ScreenStudio-中文一键安装包.zip`，内含一个安装器 `.app` 和 `先看这里.txt`。不要发开发目录、旧版本、原软件、备份、回执或个人录屏。

Python/PyInstaller 的必要许可文件包含于 App 内；翻译包仍按根目录 LICENSE 许可。Python运行时与必要的标准库随安装器携带，首次打开不联网安装依赖。PyInstaller使用 onedir，不以 root 向共享临时目录自解压。

`SCREENSTUDIO_BUILD_SDK` 可指定与 Swift 编译器匹配的 SDK。构建脚本最后执行资源自检、Swift 辅助函数测试及代码签名完整性检查，再生成 ZIP 和 SHA-256。

## 权限与恢复设计

- 普通账户运行时复用原安装器的用户资料库备份目录。
- 只有只读检查返回 WRITE_PERMISSION 才提供系统管理员授权。密码由 macOS 处理，界面不收集密码。
- 管理员运行固定使用 `/Library/Application Support/ScreenStudioChinesePatch/backups`，拒绝其他备份路径和应用程序目录之外的目标。使用 root-owned 的 0700 UUID 子目录保护备份；记录与原版副本不放进共享临时目录。
- 前端保存 app/state/elevated，恢复使用同一权限与同一回执。管理员运行不递归更改用户文件所有权。
- 提权前验证安装器签名；提权引擎额外检查自身完整性、路径、备份树所有者和写权限。原版备份再由核心安装器验签与比对完整清单。
- 固定 `lipo -archs` 调用改用严格的 Mach-O 头读取，避免系统 lipo shim要求安装开发工具。仍只接受已验证的薄 arm64 MH_EXECUTE，后续官方签名检查不变。
- 不移除 quarantine，不关闭 Gatekeeper/SIP，不读写 TCC，不自动重置权限，不修改激活和付费逻辑。

## 验收边界

```sh
python3 -m unittest discover -s desktop -p 'test_*.py' -v
python3 -m unittest discover -s package-tests -v
python3 -m unittest discover -s tests -p 'test_*.py' -v
node --test tests/localize.test.cjs
```

合成测试和安装器界面预览不等于客户机器上的真实安装、权限恢复和录屏验证。构建/验收过程不要重新安装到开发者实际使用的 Screen Studio。

熠辉课程索引中未找到直接对应 macOS 原生补丁安装器封装的课节，本次采用既有安装核心及原生界面；没有套用课程中的网站部署路线。
