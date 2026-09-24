# Protenix 结构预测测试

本项目用 Git 记录配置和实验脚本，用 Pixi 锁定运行环境。Protenix 只在 AWS 集群的 Slurm GPU 节点运行。

## 安装

项目已固定 `protenix==2.0.0`，并通过 Pixi 安装 Python 3.11、Kalign 与 HMMER。登录节点只负责提交任务：

```bash
mkdir -p logs
sbatch scripts/install.sbatch
squeue -u "$USER"
```

安装结束后查看 `logs/install-<jobid>.out`。作业会用 `pixi.lock` 在 GPU 节点安装依赖，并执行 `protenix --help` 检查 CLI。

## 预测

准备符合[官方输入格式](https://github.com/bytedance/Protenix/blob/main/docs/infer_json_format.md)的 JSON，然后提交：

```bash
mkdir -p logs
sbatch scripts/predict.sbatch input.json output/run1 protenix_base_default_v1.0.0
```

`output/`、`data/`、`logs/` 和模型权重文件不会进入 Git。首次预测可能需要下载官方模型权重或数据，因此计算节点需能访问对应资源；如集群要求离线运行，应先把资源放到共享存储并设置 `PROTENIX_ROOT_DIR`。

官方文档：[安装与推理](https://github.com/bytedance/Protenix/blob/main/docs/training_inference_instructions.md)。
