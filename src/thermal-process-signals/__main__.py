"""显示项目基本信息。"""

from . import __version__

def main() -> None:
    print(f"本地分析工作区 {__version__}")

if __name__ == "__main__":
    main()
