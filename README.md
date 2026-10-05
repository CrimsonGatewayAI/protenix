# Protenix 结构预测测试

本项目用 Git 记录配置和实验脚本，用 Pixi 锁定运行环境。依赖在当前节点安装；Protenix 预测只在 AWS 集群的 Slurm GPU 节点运行。

代码、Git 和 `.pixi/` 留在本仓库；权重、实验数据、日志和结果位于同级 `../protenix-artifacts/`。该目录处于集群导出的 `/home` 下，GPU 节点可访问。可通过绝对路径环境变量 `PROTENIX_ARTIFACTS_DIR` 指定其他共享产物根目录，用 `PROTENIX_RUN_DIR` 为新一批评测选择独立运行目录。默认目录为 `../protenix-artifacts/runs/kras-5-seeds/`。旧的 `data/`、`output/`、`logs/` 是忽略 Git 的兼容链接，保留给已有记录中的绝对路径；新代码直接读写产物目录。

修改项目时请遵循 [PR 与 Review 流程](CONTRIBUTING.md)。

## 安装

项目已固定 `protenix==2.0.0`，并通过 Pixi 安装 Python 3.11、Kalign 与 HMMER。在当前节点安装：

```bash
pixi install --locked
```

安装依据 `pixi.lock`。当前节点只检查安装，不运行结构预测。

## 集群共享副本

本集群的共享代码位于 `/shared/pipelines/protenix/`，同级的
`/shared/pipelines/protenix-artifacts/` 保存模型权重、Protenix 公共数据、参考结构、
CCD、已生成输入与历史结果。共享代码中的 `.pixi/` 从 `pixi.lock` 在该位置重新安装，
不能从其他路径直接复制虚拟环境。新任务由以下入口从任意工作目录提交：

```bash
/shared/software/bin/protenix-benchmark --check
/shared/software/bin/protenix-benchmark wt_gdp v1 101
/shared/software/bin/protenix-report
# 自备 Protenix JSON 的单次预测：
/shared/software/bin/protenix-predict /shared/home/USER/input.json
```

入口自动设置共享 Pixi 和 Slurm 路径，并将每位用户的新运行结果与 CUDA 扩展缓存
写入 `/shared/pipelines/protenix-artifacts/runs/users/<用户名>/kras-5-seeds/`。
旧运行记录中的绝对路径可能仍指向原 `/home/ubuntu/work/`；它们只作历史记录，
新任务读取共享目录下的输入和参考文件。共享的 v2 权重来源标注在
`data/protenix/checkpoint/protenix-v2.source.json` 中，不能将其视为已核实的官方权重。

## KRAS 第一轮评测

`benchmark/tasks.json` 固定七类实验结构、十一组模型任务、种子 101–105 和推理参数。输入生成器从所选 mmCIF 的实体序列、CCD 配体及显式共价连接生成产物目录下的 `data/inputs/*.json`；参考原子坐标只由独立评分器读取。`data/inputs/audit.json` 保存来源链接、SHA-256、发布日期、构建体完整序列及配体字典。任务支持一条 KRAS 蛋白链、可选的一条结合蛋白链和选定的单 CCD 配体/离子；无法表达的输入会报错。

```bash
pixi run --locked python -m benchmark.prepare
pixi run --locked python -m unittest discover -s tests -v
export PROTENIX_RUN_DIR=/home/ubuntu/work/protenix-artifacts/runs/kras-next
scripts/submit_benchmark.sh wt_gdp v2 101
```

先核对首个任务的 `metrics.json` 为 `success`、`ERR/` 为空、MSA 和 CIF 均存在，再逐项提交清单里其余任务，模型键为 `v2` 或 `v1`。请勿并发执行，以便比较单张 L40S 的算力。提交脚本把 Slurm 标准输出、监测日志和预测结构写到运行目录。作业由 Slurm 分配 AWS GPU；不在登录节点运行推理。上游 CLI 可能捕获异常并以退出码 0 返回，因此 `benchmark.run` 还要求真实的 MSA 命中、完整结构数、有限坐标和无错误文件，失败时以非零状态退出。GPU 利用率/显存逐秒写入运行目录的 `logs/gpu-<jobid>.csv`，GNU time 写入 `logs/time-<jobid>.txt`，进程树 RSS 与 CPU 使用率每秒写入任务目录的 `cpu.csv`；逐秒采样峰值只作为观测值。`metrics.json` 区分预处理、前向传播、总时间、首次资源下载和 CUDA 扩展构建/加载；首次编译对前向传播也可能另有开销。

```bash
pixi run --locked python -m benchmark.report
squeue -u "$USER"
scontrol show node gpu-dy-g6e2xlarge-1
```

报告只给成功任务计算分数。整体和口袋 Cα RMSD 采用全蛋白刚体配准；口袋定义为距关注配体 5 Å 内的实验蛋白重原子所属残基。配体重原子 RMSD 在该全蛋白配准后按 CCD 原子名比较，不另行拟合配体或最小化对称等价，因此对称配体的数值可能偏高。接触按 4 Å 重原子距离列出保留、缺失、新增；只比较实验中观察到且预测存在的原子。共价键核对所给连接两端距离，属于输入约束的几何检查，不作为独立预测证据。实验缺失的 Cα 不计入评分。单种子结果只描述一次运行，不能估计随机波动；MRTX1133 为研究化合物，结构相似度不代表药效或亲和力。

6OIM 和 6UT0 使用 G12C/C51S/C80L/C118S 构建体；7RPZ 的完整序列同样含 C51S/C80L/C118S，尽管其结构注释只列 G12D。输入匹配每个沉积序列，包括存在的 N 端残基/标签。发布日期在清单审计中记录；模型的训练数据截止日期均为 2021-09-30。截止日期之后发表的结构也不是独立盲测；本评测属于回顾性对照。

2026-10-02 的首次 v2 尝试（Slurm 9）在官方权重下载时收到 HTTP 403，见[上游相同问题](https://github.com/bytedance/Protenix/issues/294)。内部对照若使用其他来源的权重，来源、哈希及未验证的真实性必须写入忽略 Git 的本地 sidecar 和运行指标；这不能替代官方权重验证。

第二轮加入 [8BE3](https://www.rcsb.org/structure/8BE3) 的 KRAS G12V–Nanobody84 复合物。Nanobody84 是研究用纳米抗体，并非已上市抗体药；它按第二条蛋白链输入。评分先配准 KRAS，再计算纳米抗体位置 Cα RMSD 和界面残基接触 F1。此数值与小分子重原子 RMSD 不是同一指标。五种子的两张精简汇总表由以下命令生成，分别写入运行目录的 `output/performance.csv` 和 `output/resources.csv`；逐次数据写入 `output/runs.csv`，完整统计保存在 `output/performance.json` 和 `output/resources.json`。各汇总 CSV 同时包含实验结构 `ID` 和任务 `Task`（如 `wt_gdp`、`g12c_sotorasib`）。CSV 的列名和统计值使用英文及 ASCII 字符，可直接用电子表格软件打开；统计单元格显示 `mean +/- sample SD`，缺失值为 `NA`，单位 `A` 表示埃。性能表的 `Ligand/Ab RMSD A` 列按任务类型分别表示小分子重原子 RMSD 或纳米抗体位置 Cα RMSD，两者不可直接比较。

```bash
pixi run --locked python -m benchmark.repeats --usd-hour <核实的东京区g6e.2xlarge单价>
```

费用为作业占用时长乘公开 Linux 按需单价的估算；节点启动、空闲和关机时间另计，不应称为实际账单。单价来源和日期记录在运行目录的 `output/price-source.json`。

同一命令还生成 `output/confidence.csv`，汇总成功预测的原生 pLDDT、pTM、ipTM、gPDE 和 ranking score；失败与未运行样本仍保留在分母中。它们是模型自评置信度，不是相对实验结构测得的准确率。完整原始值保存在各预测的 `*_summary_confidence_sample_*.json` 和 `output/runs.csv`。

实验参考均从 RCSB PDB 下载原始 mmCIF，来源 URL、SHA-256、发布日期、所选链和输入序列记录在 `data/inputs/audit.json`。7F0W 的沉积标题明确标注 switch 1 开放构象；其较大 RMSD 必须结合构象状态解释。额外与 5US4 的事后比较使用共同的 168 残基核心序列，排除不同的 N 端构建体部分，并分别报告两条实验 KRAS 链；这不替代原 7F0W 评分，也不代表重新预测了 5US4 构建体。

所有 GPU 作业完成后，确认节点变为 `POWERED_DOWN` 且 `aws ec2 describe-instances --region ap-northeast-1 --instance-ids <GPU instance ID>` 报告 `terminated`。当前集群未启用 Slurm accounting，报告明确标记这一限制；GPU 小时以运行进程占用的 GPU 时间估计，节点启动与关机时间另见 EC2 生命周期。

## 单次预测

准备符合[官方输入格式](https://github.com/bytedance/Protenix/blob/main/docs/infer_json_format.md)的 JSON，然后提交：

```bash
scripts/submit_predict.sh input.json
```

用 `squeue -u "$USER"` 观察作业；用 `scancel <jobid>` 取消不再需要的任务。集群配置 `SuspendTime=600 sec`，空闲的 GPU 节点由 Slurm 自动关闭；作业结束后请确认节点进入 `POWERING_DOWN` 或 `POWERED_DOWN` 状态。

产物目录与模型权重文件不会进入 Git。首次预测可能需要下载官方模型权重或数据，因此计算节点需能访问对应资源；如集群要求离线运行，应先把资源放到共享存储。提交脚本会将 `PROTENIX_ROOT_DIR` 指向产物目录的 `data/protenix/`。

官方文档：[安装与推理](https://github.com/bytedance/Protenix/blob/main/docs/training_inference_instructions.md)。
