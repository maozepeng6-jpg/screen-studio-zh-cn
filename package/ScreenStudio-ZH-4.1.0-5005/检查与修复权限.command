#!/bin/zsh
# Only the Python helper can run tccutil; it enforces bundle/service/confirmation checks.
set -u
PACKAGE_DIR="${0:A:h}"
if ! command -v python3 >/dev/null 2>&1; then
  print -r -- '需要 Python 3.9 或更新版本。请从可信来源安装后重试。'
  exit 1
fi
if (( $# > 0 )); then
  exec python3 "$PACKAGE_DIR/repair_permissions.py" "$@"
fi
print -r -- '先做只读检查，不会重置权限，也不会替你授权。'
python3 "$PACKAGE_DIR/repair_permissions.py" --check
if (( $? != 0 )); then
  print -r -- '检查未完成，请保留上方错误信息；不会继续重置。'
  read -r '?按回车关闭。'
  exit 1
fi
print -r -- '若只是查看结果，直接按回车退出。仅在权限故障时选择：'
print -r -- '1 = 屏幕录制与辅助功能；2 = 仅屏幕录制；3 = 仅辅助功能'
print -r -- '4 = 仅麦克风；5 = 仅摄像头。麦克风/摄像头不是录屏必需。'
read -r 'choice?选择：'
typeset -a services
case "$choice" in
  1) services=(ScreenCapture Accessibility) ;;
  2) services=(ScreenCapture) ;;
  3) services=(Accessibility) ;;
  4) services=(Microphone) ;;
  5) services=(Camera) ;;
  *) print -r -- '已退出，未重置权限。'; exit 0 ;;
esac
print -r -- "将仅撤销 com.timpler.screenstudio 的旧授权：${services[*]}。"
print -r -- '请先保存工作并彻底退出 Screen Studio。之后你需要在 macOS 中重新授权。'
print -r -- '不会自动点同意、不会处理其他应用；若要继续，请完整输入 REPAIR。'
read -r 'confirmation?确认：'
if [[ "$confirmation" != REPAIR ]]; then
  print -r -- '已取消，未重置权限。'
  exit 0
fi
python3 "$PACKAGE_DIR/repair_permissions.py" --repair --confirm --services "${services[@]}"
result=$?
read -r '?请阅读上方结果与重新授权步骤。按回车关闭。'
exit "$result"
