# Protenix 结构预测测试

本项目用 Git 记录配置和实验脚本，用 Pixi 锁定运行环境。依赖在当前节点安装；Protenix 预测只在 AWS 集群的 Slurm GPU 节点运行。

修改项目时请遵循 [PR 与 Review 流程](CONTRIBUTING.md)。

## 安装

项目已固定 `protenix==2.0.0`，并通过 Pixi 安装 Python 3.11、Kalign 与 HMMER。在当前节点安装：

```bash
pixi install --locked
```

安装依据 `pixi.lock`。当前节点只检查安装，不运行结构预测。

## KRAS 第一轮评测

`benchmark/tasks.json` 固定六类实验结构、九个模型任务和推理参数。输入生成器从所选 mmCIF 的实体序列、CCD 配体及显式共价连接生成 `data/inputs/*.json`；参考原子坐标只由独立评分器读取。`data/inputs/audit.json` 保存来源链接、SHA-256、发布日期、构建体完整序列及配体字典。任务限于一个标准氨基酸蛋白链和选定的单 CCD 配体/离子；无法表达的输入会报错。

```bash
pixi run --locked python -m benchmark.prepare
pixi run --locked python -m unittest discover -s tests -v
mkdir -p logs
sbatch scripts/benchmark.sbatch wt_gdp v2 output/wt_gdp-v2
```

先核对首个任务的 `metrics.json` 为 `success`、`ERR/` 为空、MSA 和 CIF 均存在，再逐项提交清单里其余任务，模型键为 `v2` 或 `v1`。请勿并发执行，以便比较单张 L40S 的算力。作业由 Slurm 分配 AWS GPU；不在登录节点运行推理。上游 CLI 可能捕获异常并以退出码 0 返回，因此 `benchmark.run` 还要求真实的 MSA 命中、完整结构数、有限坐标和无错误文件，失败时以非零状态退出。GPU 利用率/显存逐秒写入 `logs/gpu-<jobid>.csv`，GNU time 写入 `logs/time-<jobid>.txt`，进程树 RSS 写入运行目录 `cpu.csv`。`metrics.json` 区分预处理、前向传播、总时间、首次资源下载和 CUDA 扩展构建/加载；首次编译对前向传播也可能另有开销。

```bash
pixi run --locked python -m benchmark.report
squeue -u "$USER"
scontrol show node gpu-dy-g6e2xlarge-1
```

报告只给成功任务计算分数。整体和口袋 Cα RMSD 采用全蛋白刚体配准；口袋定义为距关注配体 5 Å 内的实验蛋白重原子所属残基。配体重原子 RMSD 在该全蛋白配准后按 CCD 原子名比较，不另行拟合配体或最小化对称等价，因此对称配体的数值可能偏高。接触按 4 Å 重原子距离列出保留、缺失、新增；只比较实验中观察到且预测存在的原子。共价键核对所给连接两端距离，属于输入约束的几何检查，不作为独立预测证据。实验缺失的 Cα 不计入评分。单种子结果只描述一次运行，不能估计随机波动；MRTX1133 为研究化合物，结构相似度不代表药效或亲和力。

6OIM 和 6UT0 使用 G12C/C51S/C80L/C118S 构建体；7RPZ 的完整序列同样含 C51S/C80L/C118S，尽管其结构注释只列 G12D。输入匹配每个沉积序列，包括存在的 N 端残基/标签。发布日期在清单审计中记录；模型的训练数据截止日期均为 2021-09-30。截止日期之后发表的结构也不是独立盲测；本评测属于回顾性对照。

2026-10-02 的首次 v2 尝试（Slurm 9）在官方权重下载时收到 HTTP 403，见[上游相同问题](https://github.com/bytedance/Protenix/issues/294)。结果表明确标记其余 v2 任务受该权重阻断；有合法的官方 v2 检查点可用后，放在 `data/protenix/checkpoint/protenix-v2.pt` 并重新提交 v2 作业。当前完成的三个 v1 作业与 v2 没有可计算的模型间对照差异。

所有 GPU 作业完成后，确认节点变为 `POWERED_DOWN` 且 `aws ec2 describe-instances --region ap-northeast-1 --instance-ids <GPU instance ID>` 报告 `terminated`。当前集群未启用 Slurm accounting，报告明确标记这一限制；GPU 小时以运行进程占用的 GPU 时间估计，节点启动与关机时间另见 EC2 生命周期。

## 单次预测

准备符合[官方输入格式](https://github.com/bytedance/Protenix/blob/main/docs/infer_json_format.md)的 JSON，然后提交：

```bash
mkdir -p logs
sbatch scripts/predict.sbatch input.json output/run1 protenix_base_default_v1.0.0
```

用 `squeue -u "$USER"` 观察作业；用 `scancel <jobid>` 取消不再需要的任务。集群配置 `SuspendTime=600 sec`，空闲的 GPU 节点由 Slurm 自动关闭；作业结束后请确认节点进入 `POWERING_DOWN` 或 `POWERED_DOWN` 状态。

`output/`、`data/`、`logs/` 和模型权重文件不会进入 Git。首次预测可能需要下载官方模型权重或数据，因此计算节点需能访问对应资源；如集群要求离线运行，应先把资源放到共享存储并设置 `PROTENIX_ROOT_DIR`。

官方文档：[安装与推理](https://github.com/bytedance/Protenix/blob/main/docs/training_inference_instructions.md)。
