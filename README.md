# 炉线换配方后的异常证据与处置范围

这是用于工艺时序与批次质量分析的本地工作区。样例资料为合成数据，不代表真实生产或检测记录。工作区包含 Python 3.11+ 命令入口和 JSON 记录，可离线查看与核验。

## 运行

无需安装第三方依赖。设置 `PYTHONPATH=src` 后运行 `python3 -m thermal-process-signals` 可查看工作区版本。运行现有基线检查：`PYTHONPATH=src python3 -m unittest discover -s tests -v`。

## 资料

`data/sample.json` 保存小型合成记录，顶层键分别为 sensors, process, reviews。
