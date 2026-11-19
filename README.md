# 炉线换配方后的异常证据与处置范围

这是用于工艺时序与批次质量分析的本地工作区。样例资料为合成数据，不代表真实生产或检测记录。工作区包含 Python 3.11+ 命令入口和 JSON 记录，可离线查看与核验。

## 运行

无需安装第三方依赖。设置 `PYTHONPATH=src` 后运行 `python3 -m thermal-process-signals` 可查看工作区版本。运行现有基线检查：`PYTHONPATH=src python3 -m unittest discover -s tests -v`。

## 资料

`data/sample.json` 保存小型合成记录，顶层键分别为 sensors, process, reviews。

`data/shift_handoff.json` 保存两条炉线交班资料。测点是摄氏温度，`value: null` 表示设备未采到值；`phase` 分开记录预热、换配方和稳定过程。`reference_log` 是值班登记的参考候选日，不表示其中所有读数均已获认可，其中换配方前另有同一配方的试产记录。所有时间采用工厂本地时间，停留区间左闭右开。

`route_log.station` 的 `feed` 是共用进料点，其余为炉线；`corrects` 引用被更正的卡，`filed_at` 是值班获知时间，`start_slack_minutes` 表示开始时刻前后可能的分钟误差。隔离卡中的范围是开卡时记录的异常工况区间，不是批次的全部停留时间。抽检的 `begin`、`end` 是记录所覆盖的生产区间，不是抽检时间；`recorded` 是结论入账时间。
