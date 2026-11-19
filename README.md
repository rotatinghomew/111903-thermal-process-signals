# 炉线换配方后的异常证据与处置范围

这是围绕炉线换配方后的异常证据与处置范围整理的本地合成数据分析工作区。数据仅为演练构造，不代表真实企业或检测记录。项目当前提供 Python 3.11+ 的基础命令入口和 JSON 合成资料；业务分析流程尚未包含。

## 运行

无需安装第三方依赖。设置 `PYTHONPATH=src` 后运行 `python3 -m thermal-process-signals` 可查看工作区版本。运行现有基线检查：`PYTHONPATH=src python3 -m unittest discover -s tests -v`。

## 资料

`data/sample.json` 保存小型合成记录，顶层键分别为 sensors, process, reviews。
