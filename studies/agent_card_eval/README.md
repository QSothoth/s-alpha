# agent_card_eval：agent 审卡评测

择时规则出入场信号后，由 agent（Codex、Claude、Grok 等不同 harness 加不同模型）决定接受还是拒绝。本切片把这一步做成可复现的评测：从冻结数据集生成匿名卡片，让 agent 判断，再用 custody 回放的真实期权盈亏计分，和"全部接受"以及"随机挑同样张数"比较。

## 结论

| 轮次 | 被测 | 结果 |
|---|---|---|
| [A1](notes/A1_PREREG.md) | Codex（gpt-6.1-sol）审 v6.6 卡片 | **未通过**：接受 9/96，接受部分 −155 美元，全部接受 +612 美元；相对随机 p = 0.85。赚钱的 22 张只接受 1 张。见 [结果](reports/A1_RESULTS_CN.md) |
| [A2](notes/A2_PREREG.md) | 四个改法：告诉收益结构、改打分排序、加摘要、提高推理强度 | **失败**：三个退化为全部接受（+605 对 +612 美元），打分版的概率没有信息（+41 美元）；09-25 验证段未使用。见 [结果](reports/A2_RESULTS_CN.md) |

目前没有任何证据表明 agent 审卡能提高收益：不知道收益结构时它系统性砍掉赢单，知道以后几乎全接受，打分则给出噪声。在有新证据之前，审卡不应否决 v6.6 的信号；agent 的价值在执行与运维。

## 代码

- `code/cards.py`：从数据集生成卡片（`cards.jsonl`，给 agent）和结果（`outcomes.jsonl`，只用于计分）。
- `code/prompt.txt`：A1 提示词；`prompt_b1.txt` / `prompt_b2.txt` / `prompt_b3.txt`：A2 候选。卡片可加 `--summary` 生成确定性摘要（B3）；`run.py --effort` 覆盖 Codex 推理强度（B4）；`score.py --skip-lowest` 按概率排序计分（B2）。
- `code/run.py`：调用 `codex` / `claude` / `grok`，每张卡多次，原始输出逐次落盘，可断点续跑。
- `code/score.py`：多数票、与全部接受和随机挑选比较、按交易日重抽样。

测试：`python3 -m unittest discover -s studies/agent_card_eval/tests`。原始输出在本机 `data/agent-card-eval-a1/`、`data/agent-card-eval-a2/`，不进 git。
