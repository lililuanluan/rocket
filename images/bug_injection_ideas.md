# Rippled 共识协议 Bug 注入清单

## 已有 Bug（d4f7fe72bb）分析

已复现的 bug 来自 PR #4424，位于 `Validations.h` 中的 `getTrustedForLedger()`。
该 bug 移除了 `v.seq() == seq` 检查，导致不同 sequence 的 validation 被混在一起返回。
这是一个比较"粗暴"的 bug——破坏了 validation 过滤的基本正确性，影响面非常广
（LedgerMaster::checkAccept、RCLConsensus::onClose、NegativeUNLVote::buildScoreTable 等
6 个调用点全部受影响），因此很容易被 evotest 发现。

---

## 新 Bug 注入点分析

以下按**难度递增**排列，难度越高意味着 evotest 越难检测到。

---

### 类别 A：共识阈值/Quorum 相关

#### A1. 修改 `minCONSENSUS_PCT` 阈值
- **文件**: `src/xrpld/consensus/ConsensusParms.h`
- **位置**: `std::size_t const minCONSENSUS_PCT = 80;`
- **注入方式**: 将 80 改为 60 或 50
- **效果**: 降低达成共识所需的比例，可能导致在不够多节点同意时就宣布共识，增加分叉风险
- **检测难度**: ⭐⭐ 中等。需要特定的网络分区/延迟条件才能触发分叉

#### A2. 修改 `calculateQuorum()` 的 0.8 系数
- **文件**: `src/xrpld/app/misc/detail/ValidatorList.cpp:1907`
- **位置**: `std::ceil(effectiveUnlSize * 0.8f)`
- **注入方式**: 改为 `std::ceil(effectiveUnlSize * 0.6f)` 或 `0.5f`
- **效果**: 降低 quorum 门槛，使得更少的 validation 就能确认一个 ledger
- **检测难度**: ⭐⭐ 中等。需要多节点间出现分歧时才能触发

#### A3. 修改 `checkConsensusReached()` 中的自计票逻辑
- **文件**: `src/xrpld/consensus/Consensus.cpp:158-163`
- **位置**:
  ```cpp
  if (count_self)
  {
      ++agreeing;
      ++total;
  }
  ```
- **注入方式**: 只增加 `agreeing` 不增加 `total`（即自己总是同意但不计入总数），或反过来
- **效果**: 人为膨胀或压缩共识百分比
- **检测难度**: ⭐⭐⭐ 较难。效果微妙，在大多数正常情况下不会触发问题

#### A4. `participantsNeeded()` 取整偏差
- **文件**: `src/xrpld/consensus/Consensus.h:1477-1483`
- **位置**:
  ```cpp
  int result = ((participants * percent) + (percent / 2)) / 100;
  return (result == 0) ? 1 : result;
  ```
- **注入方式**: 去掉 `(percent / 2)` 的四舍五入修正，或将 `result == 0` 改为 `return 0`
- **效果**: 在边界情况（少量参与者）可能导致需要的同意数过低或为零
- **检测难度**: ⭐⭐⭐ 较难。仅在参与者较少时触发

---

### 类别 B：Validation 收集与过滤

#### B5. `isCurrent()` 放宽时间窗口
- **文件**: `src/xrpld/consensus/Validations.h:155-166`
- **位置**:
  ```cpp
  return (signTime > (now - p.validationCURRENT_EARLY)) &&
      (signTime < (now + p.validationCURRENT_WALL)) &&
      ((seenTime == NetClock::time_point{}) ||
       (seenTime < (now + p.validationCURRENT_LOCAL)));
  ```
- **注入方式**: 移除 `signTime > (now - p.validationCURRENT_EARLY)` 条件，允许过时的 validation 被接受
- **效果**: 过期的 validation 不会被清理，导致节点基于过时信息做决策
- **检测难度**: ⭐⭐⭐ 较难。需要特定时序才能暴露

#### B6. `SeqEnforcer` 单调递增检查绕过
- **文件**: `src/xrpld/consensus/Validations.h:113-125`
- **位置**:
  ```cpp
  bool operator()(time_point now, Seq s, ValidationParms const& p)
  {
      if (now > (when_ + p.validationSET_EXPIRES))
          seq_ = Seq{0};
      if (s <= seq_)
          return false;
      seq_ = s;
      when_ = now;
      return true;
  }
  ```
- **注入方式**: 将 `s <= seq_` 改为 `s < seq_`（允许相同 seq 重复）
- **效果**: 允许同一 validator 为相同 sequence 发送多个不同的 validation，绕过拜占庭检测
- **检测难度**: ⭐⭐⭐⭐ 困难。这是拜占庭行为检测的核心，但正常情况下不会有重复 seq

#### B7. `numTrustedForLedger()` 不检查 `full()` 状态
- **文件**: `src/xrpld/consensus/Validations.h:1038-1050`
- **位置**:
  ```cpp
  [&](NodeID const&, Validation const& v) {
      if (v.trusted() && v.full())
          ++count;
  });
  ```
- **注入方式**: 移除 `v.full()` 检查，让 partial validation 也被计入
- **效果**: partial validation（不完整确认）被计入信任数，可能虚假膨胀 trusted validation 数量
- **检测难度**: ⭐⭐⭐ 较难。需要存在 partial validation 才能触发差异

#### B8. `negativeUNLFilter()` 失效
- **文件**: `src/xrpld/app/misc/detail/ValidatorList.cpp:2135-2165`
- **注入方式**: 让 filter 始终返回未过滤的原始列表（注释掉 `erase(remove_if(...))` 逻辑）
- **效果**: 被列入 Negative UNL 的恶意/离线节点的 validation 不再被过滤，
  可能导致不可靠节点影响共识结果
- **检测难度**: ⭐⭐⭐⭐ 困难。需要 Negative UNL 机制被激活且节点确实在 nUNL 中

---

### 类别 C：提案/投票逻辑

#### C9. `peerProposalInternal()` 中 prevLedger 检查移除
- **文件**: `src/xrpld/consensus/Consensus.h:730-735`
- **位置**:
  ```cpp
  if (newPeerProp.prevLedger() != prevLedgerID_)
  {
      JLOG(j_.debug()) << "Got proposal for " << newPeerProp.prevLedger()
                       << " but we are on " << prevLedgerID_;
      return false;
  }
  ```
- **注入方式**: 注释掉这个检查，允许基于不同 prevLedger 的提案被接受
- **效果**: 节点可能接受基于错误前序 ledger 的提案，导致对不同交易集合的混乱投票
- **检测难度**: ⭐⭐ 中等

#### C10. `proposeSeq` 单调递增检查移除
- **文件**: `src/xrpld/consensus/Consensus.h:748-753`
- **位置**:
  ```cpp
  if (newPeerProp.proposeSeq() <=
      peerPosIt->second.proposal().proposeSeq())
  {
      return false;
  }
  ```
- **注入方式**: 去掉此检查，允许旧序号的提案覆盖新的
- **效果**: 攻击者可以"回滚"其提案到之前的位置，导致投票混乱
- **检测难度**: ⭐⭐⭐ 较难

#### C11. `DisputedTx::updateVote()` 中投票权重计算错误
- **文件**: `src/xrpld/consensus/DisputedTx.h:298-305`
- **位置**:
  ```cpp
  if (proposing)  // give ourselves full weight
  {
      weight = (yays_ * 100 + (ourVote_ ? 100 : 0)) / (nays_ + yays_ + 1);
      newPosition = weight > requiredPct;
  }
  ```
- **注入方式**: 
  - 将 `nays_ + yays_ + 1` 改为 `nays_ + yays_`（除零风险 + 权重错误）
  - 或将 `>` 改为 `>=`（降低阈值）
  - 或将 `(ourVote_ ? 100 : 0)` 改为 `(ourVote_ ? 0 : 100)`（反转自己的票）
- **效果**: 可能导致争议交易的包含/排除决策错误
- **检测难度**: ⭐⭐⭐ 较难。需要存在 disputed transactions

#### C12. Avalanche 阈值递增逻辑错误
- **文件**: `src/xrpld/consensus/ConsensusParms.h:152-161`
- **位置**: `avalancheCutoffs` map
- **注入方式**: 修改 `stuck` 状态的阈值从 95 改为 50，或交换 `mid` 和 `late` 的百分比
- **效果**: 共识进入"卡住"状态时使用错误的接受阈值，可能导致不安全的交易被接受
- **检测难度**: ⭐⭐⭐⭐ 困难。需要共识进入后期阶段才能触发

---

### 类别 D：时间/Close 相关

#### D13. `shouldCloseLedger()` 中关闭条件过早
- **文件**: `src/xrpld/consensus/Consensus.cpp:69-73`
- **位置**:
  ```cpp
  if ((proposersClosed + proposersValidated) > (prevProposers / 2))
  ```
- **注入方式**: 将 `/ 2` 改为 `/ 4` 或直接改为 `> 0`
- **效果**: 更少的节点关闭就触发本节点关闭 ledger，可能导致节点过早关闭
- **检测难度**: ⭐⭐ 中等

#### D14. `closeLedger()` 后的 Close Time Consensus 检查绕过
- **文件**: `src/xrpld/consensus/Consensus.h:1414-1419`
- **位置**:
  ```cpp
  if (!haveCloseTimeConsensus_)
  {
      JLOG(j_.info()) << "We have TX consensus but not CT consensus";
      return;
  }
  ```
- **注入方式**: 注释掉这个检查，即使 close time 没有达成共识也继续
- **效果**: close time 可能不一致，导致后续 ledger 的时间计算出现偏差
- **检测难度**: ⭐⭐⭐ 较难。通常 close time 会很快达成一致

#### D15. `avCT_CONSENSUS_PCT` 降低
- **文件**: `src/xrpld/consensus/ConsensusParms.h:169`
- **位置**: `std::size_t const avCT_CONSENSUS_PCT = 75;`
- **注入方式**: 改为 50 或 40
- **效果**: 更少节点同意就能达成 close time 共识，可能导致 close time 不准确
- **检测难度**: ⭐⭐⭐ 较难

#### D16. `roundCloseTime()` 取整错误
- **文件**: `src/xrpld/consensus/LedgerTiming.h:138-147`
- **位置**:
  ```cpp
  closeTime += (closeResolution / 2);
  return closeTime - (closeTime.time_since_epoch() % closeResolution);
  ```
- **注入方式**: 去掉 `+= (closeResolution / 2)` 使得总是向下取整，或加上整个 `closeResolution` 使得总是向上取整
- **效果**: 所有节点的 close time 取整方式不一致，可能导致 close time 分歧
- **检测难度**: ⭐⭐⭐⭐ 困难。仅在 close time 恰好在取整边界时触发

---

### 类别 E：Ledger 接受与验证

#### E17. `checkAccept()` 跳过 sequence 检查
- **文件**: `src/xrpld/app/ledger/detail/LedgerMaster.cpp:883-885`
- **位置**:
  ```cpp
  if (seq < mValidLedgerSeq)
      return;
  ```
- **注入方式**: 将 `<` 改为 `<=`（阻止同 seq 的 re-validation），或直接移除此检查（允许回退到旧 ledger）
- **效果**: 
  - `<=`: 可能在竞争条件下阻止正确的 ledger 被接受
  - 移除: 可能接受旧的 ledger，导致状态回滚
- **检测难度**: ⭐⭐⭐ 较难

#### E18. `canValidateSeq()` 绕过
- **文件**: `src/xrpld/consensus/Validations.h:616-620`
- **位置**: `localSeqEnforcer_(byLedger_.clock().now(), s, parms_);`
- **注入方式**: 直接返回 `true`，绕过单调递增检查
- **效果**: 节点可以为比之前 validation 更低的 seq 发送新的 validation
- **检测难度**: ⭐⭐⭐ 较难

#### E19. `doAccept()` 中 consensusFail 检查绕过
- **文件**: `src/xrpld/app/consensus/RCLConsensus.cpp:555-561`
- **位置**:
  ```cpp
  if (validating_ && !consensusFail &&
      app_.getValidations().canValidateSeq(built.seq()))
  {
      validate(built, result.txns, proposing);
  }
  ```
- **注入方式**: 移除 `!consensusFail` 条件
- **效果**: 即使共识失败（MovedOn 状态），节点仍然发送 validation，
  可能导致其他节点错误地接受一个有争议的 ledger
- **检测难度**: ⭐⭐⭐⭐ 困难。需要共识进入 MovedOn 状态

---

### 类别 F：LedgerTrie / Preferred Ledger

#### F20. `getPreferred()` 中分支偏好逻辑错误
- **文件**: `src/xrpld/consensus/Validations.h:918-931`
- **位置**:
  ```cpp
  // A ledger ahead of us is preferred regardless
  if (preferred->seq > curr.seq())
      return std::make_pair(preferred->seq, preferred->id);
  
  // Only switch to earlier or same sequence number
  // if it is a different chain.
  if (curr[preferred->seq] != preferred->id)
      return std::make_pair(preferred->seq, preferred->id);
  ```
- **注入方式**: 反转第一个条件 (`preferred->seq < curr.seq()`)
  或移除"不同链"的检查
- **效果**: 节点可能错误地切换到较短或不相关的分支
- **检测难度**: ⭐⭐⭐⭐ 困难。需要存在分叉/分支竞争

#### F21. `getPrevLedger()` 返回值篡改
- **文件**: `src/xrpld/app/consensus/RCLConsensus.cpp:295-309`
- **注入方式**: 始终返回 `ledgerID` 而不是 `netLgr`（即忽略网络偏好）
- **效果**: 节点永远不会跟随网络切换到正确的 ledger 分支
- **检测难度**: ⭐⭐⭐ 较难

---

### 类别 G：Negative UNL 投票

#### G22. `buildScoreTable()` 中的分数计算错误
- **文件**: `src/xrpld/app/misc/NegativeUNLVote.cpp:205-212`
- **位置**:
  ```cpp
  for (int i = 0; i < FLAG_LEDGER_INTERVAL; ++i)
  {
      for (auto const& v : validations.getTrustedForLedger(
               ledgerAncestors[numAncestors - 1 - i], seq - 2 - i))
  ```
- **注入方式**: 将索引从 `numAncestors - 1 - i` 改为 `i`（正序而非倒序）
- **效果**: 查询错误的 ledger hash 对应的 validation，导致 score table 数据全部错误，
  从而错误地将在线节点加入 negative UNL 或不移除离线节点
- **检测难度**: ⭐⭐⭐⭐ 困难。需要 flag ledger 且有节点行为异常

#### G23. `negativeUNLLowWaterMark` / `negativeUNLHighWaterMark` 交换
- **文件**: `src/xrpld/app/misc/NegativeUNLVote.h` (常量定义)
- **注入方式**: 交换低水位和高水位的值
- **效果**: 可靠的节点被列入 nUNL，不可靠的节点反而被重新启用
- **检测难度**: ⭐⭐⭐⭐⭐ 非常困难。仅在 nUNL 投票逻辑被实际调用时有影响

---

### 类别 H：Stale/Expiry 检查

#### H24. Proposal Freshness 检查放宽
- **文件**: `src/xrpld/consensus/ConsensusParms.h:73`
- **位置**: `std::chrono::seconds const proposeFRESHNESS = std::chrono::seconds{20};`
- **注入方式**: 改为 `std::chrono::seconds{600}`（10分钟）
- **效果**: 过期的提案不会被清理，节点可能基于非常旧的提案做决策
- **检测难度**: ⭐⭐⭐ 较难

#### H25. `validationVALID_WALL` 超长窗口
- **文件**: `src/xrpld/consensus/ConsensusParms.h:52`
- **位置**: `std::chrono::seconds const validationVALID_WALL = std::chrono::minutes{5};`
- **注入方式**: 改为 `std::chrono::hours{1}`
- **效果**: 极其过时的 validation 仍被认为有效，可能导致已停机节点的旧 validation 继续影响共识
- **检测难度**: ⭐⭐⭐⭐ 困难。正常运行时不会有这么旧的 validation

---

## 推荐优先注入的 Bug（按 evotest 检测难度排序）

### 🟢 容易发现（适合验证 evotest 基本能力）
1. **A1** - `minCONSENSUS_PCT` 降低（80→50）
2. **C9** - prevLedger 检查移除
3. **D13** - shouldCloseLedger 过早关闭

### 🟡 中等难度（适合测试遗传算法的优化能力）
4. **A3** - checkConsensusReached 自计票逻辑错误
5. **B7** - numTrustedForLedger 不检查 full()
6. **C11** - DisputedTx 投票权重计算错误
7. **D14** - Close Time Consensus 检查绕过
8. **E19** - consensusFail 时仍发送 validation

### 🔴 困难（需要精心设计的延迟策略才能触发）
9. **B6** - SeqEnforcer 单调递增检查绕过（`<=` → `<`）
10. **C12** - Avalanche 阈值错误
11. **D16** - roundCloseTime 取整错误
12. **F20** - getPreferred 分支偏好逻辑反转

### ⚫ 极度困难（可能需要特殊网络条件）
13. **B8** - negativeUNLFilter 失效
14. **G22** - NegativeUNL Score Table 索引错误
15. **G23** - nUNL 水位线交换

---

## 注入建议

1. **每次只注入一个 bug**，保持其他代码不变，这样可以精确评估 evotest 的检测能力
2. **优先从 🟡 中等难度开始**，这些 bug 足够微妙但不需要极特殊条件
3. **创建独立的 git 分支**，如 `byzz-bug-inject-A1`、`byzz-bug-inject-C11` 等
4. **每个 bug 对应一个 Dockerfile**，类似 `Dockerfile.rippled-2.6.0-byzz-bug-XXX`
5. 对于 🔴 困难级别的 bug，需要在 `evo/evotest.yaml` 中调大 `max_ledger_seq`
   和迭代次数，给遗传算法更多搜索空间

## 关于 evotest 检测能力的预测

| Bug | 预期可检测到的 spec_check 失败类型 |
|-----|------|
| A1, A2 | `same_ledger_hashes = False`（分叉） |
| A3, A4 | `same_ledger_hashes = False`（边界情况下分叉） |
| B5, B6 | `same_ledger_hashes = False`（错误 validation 导致分叉） |
| B7 | `same_ledger_hashes = False`（虚假膨胀导致过早接受） |
| C9, C10 | `same_ledger_hashes = False`（混乱提案导致不同共识结果） |
| C11, C12 | `same_ledger_hashes = False` 或 `reached_goal_ledger = False`（卡住） |
| D13 | `reached_goal_ledger = False`（过早关闭导致超时） |
| D14, D15, D16 | `same_ledger_hashes = False`（close time 不一致导致不同 ledger hash） |
| E17, E18, E19 | `same_ledger_hashes = False`（错误接受/回退） |
| F20, F21 | `reached_goal_ledger = False`（节点卡在错误分支） |
| G22, G23 | 可能不会直接导致失败，但会导致性能异常（mean_validation_time 升高） |

---
---

# 第二部分：微妙 Bug 注入（Subtle Mutations）

上面的注入方式（A1–H25）相对"直接"——移除整个检查、大幅修改常量值等。
以下是更**微妙**的注入方式：每个变异只改动一个运算符、一个边界值、或一个微小的算术细节。
这些 bug 看起来像是**真正的程序员失误**（off-by-one、比较符写反、整数除法精度问题），
只在特定的时序或网络条件下才会触发，常规测试极难发现。

---

## 类别 SA — 整数算术与取整

### SA1. `participantsNeeded()` 取整偏移 +1

**文件:** `Consensus.h`（约第 1487 行）

```cpp
// 原始:
int result = ((participants * percent) + (percent / 2)) / 100;

// 变异:
int result = ((participants * percent) + (percent / 2) + 1) / 100;
```

**为什么微妙:** `+ (percent/2)` 是四舍五入技巧。多加一个 `+1` 只在特定的
`(participants, percent)` 组合恰好处于取整边界时才改变结果。常见的 5 节点配置下
大多数阈值计算不受影响，只有在罕见的验证者数量下才会导致所需同意数偏移一个。

---

### SA2. `checkConsensusReached` 百分比比较: `>=` → `>`

**文件:** `Consensus.cpp`（约第 150 行）

```cpp
// 原始:
return currentPercentage >= minConsensusPct;

// 变异:
return currentPercentage > minConsensusPct;
```

**为什么微妙:** 把"大于等于 80%"改为"严格大于 80%"。5 个验证者时，4/5 = 80%，
原始代码 80% ≥ 80% → 共识达成；变异后 80% > 80% → 不成立，需要 5/5（100%）。
这是一个时序相关的 bug：如果所有节点最终都同意则不触发，但只要有一个节点稍慢，
共识就会卡住直到超时回退机制介入。

---

### SA3. `DisputedTx::updateVote()` 权重除数偏移

**文件:** `DisputedTx.h`（约第 308 行）

```cpp
// 原始:
weight = (yays_ * 100 + (ourVote_ ? 100 : 0)) / (nays_ + yays_ + 1);

// 变异:
weight = (yays_ * 100 + (ourVote_ ? 100 : 0)) / (nays_ + yays_ + 2);
```

**为什么微妙:** 分母中的 `+1` 表示"自己"。改为 `+2` 后所有权重都略微偏低。
4 yays、0 nays、ourVote=true 时：原始 weight = 500/5 = 100，变异后 = 500/6 = 83。
只有当权重恰好接近 avalanche 阈值边界（50–70%）时才会翻转交易的命运。
效果是在 avalanche 过程中稍微倾向于**丢弃**交易，且仅在投票数少且接近阈值时才显现。

---

### SA4. `convergePercent_` 分母偏移

**文件:** `Consensus.h`（约第 1383 行）

```cpp
// 原始:
convergePercent_ = prevRoundTime_.count()
    ? (100 * result_->roundTime.read().count() /
       prevRoundTime_.count())
    : 0;

// 变异:
convergePercent_ = prevRoundTime_.count()
    ? (result_->roundTime.read().count() * 100 /
       (prevRoundTime_.count() + 1))
    : 0;
```

**为什么微妙:** 分母加 `+1` 使 `convergePercent_` 略低，导致 `getNeededWeight()` 中
的 avalanche 权重阈值转换延后——系统在较低阈值（50%）上多停留一会儿。
正常情况下（快速共识）完全没有影响，只有当某一轮共识时间刚好接近状态转换边界时才触发。

---

## 类别 SB — 比较运算与边界条件

### SB1. `shouldCloseLedger()` 多数条件偏移

**文件:** `Consensus.cpp`（约第 83 行）

```cpp
// 原始:
if ((proposersClosed + proposersValidated) > (prevProposers / 2))

// 变异:
if ((proposersClosed + proposersValidated) >= (prevProposers / 2))
```

**为什么微妙:** "严格多数"变为"半数或以上"。`prevProposers = 4` 时，原始需要 > 2
（即 3+），变异后需要 ≥ 2。这让节点稍微提前关闭 ledger，通常无害，但在高延迟下可能
导致节点在对端还没共享完交易集时就关闭了，从而以不同的初始位置开始共识。

---

### SB2. `checkConsensus()` 3/4 出席检查附加条件

**文件:** `Consensus.cpp`（约第 196 行）

```cpp
// 原始:
if (currentProposers < (prevProposers * 3 / 4))

// 变异:
if (currentProposers < (prevProposers * 3 / 4) && currentProposers > 0)
```

**为什么微妙:** 多加的 `&& currentProposers > 0` 意味着当 `currentProposers == 0` 时
这个守卫被跳过，代码继续执行到正常共识检查。此时 agreeing 也为 0，
`checkConsensusReached(0, 0, 80)` 判定 `0 >= 80` → false。所以这个 bug 只在
一个极端的边缘情况下起作用：零当前提议者 + 满足时间条件 → 返回 `MovedOn` 而不是 `No`。

---

### SB3. `getNextLedgerTimeResolution()` 取模条件翻转

**文件:** `LedgerTiming.h`（约第 116 行）

```cpp
// 原始:
if (!previousAgree &&
    (ledgerSeq % Seq{decreaseLedgerTimeResolutionEvery} == Seq{0}))

// 变异:
if (!previousAgree &&
    (ledgerSeq % Seq{decreaseLedgerTimeResolutionEvery} != Seq{0}))
```

**为什么微妙:** `decreaseLedgerTimeResolutionEvery` 值为 1，所以 `ledgerSeq % 1`
**永远**等于 0。因此 `== 0` 总是 true，`!= 0` 总是 false。变异后，当节点对 close time
不一致时，分辨率永远不会降低（不会变粗）。这个 bug 极度休眠：只在 close time 出现分歧
且持续多轮时才激活。效果是分辨率保持过细，使未来的分歧更容易发生，形成级联效应。

---

### SB4. `Validations::add()` signTime 替换方向

**文件:** `Validations.h`（约第 691 行）

```cpp
// 原始:
if (val.signTime() > oldVal.signTime())

// 变异:
if (val.signTime() >= oldVal.signTime())
```

**为什么微妙:** `>` 变 `>=` 意味着相同 signTime 的 validation 也会替换已有的。
正常运行时每个 validation 的 signTime 都是唯一的，所以永远不触发。但如果两个
validation 恰好在同一秒边界到达，后到的那个会无条件替换前者，可能导致 trie 条目
短暂不一致。这是一个只在特定时钟对齐条件下才触发的竞态 bug。

---

## 类别 SC — Avalanche 状态机

### SC1. `getNeededWeight()` 中间状态阈值边界

**文件:** `ConsensusParms.h`（约第 180 行）

```cpp
// 原始:
if (percentTime < avMID_CONSENSUS_TIME)

// 变异:
if (percentTime <= avMID_CONSENSUS_TIME)
```

**为什么微妙:** 当 `convergePercent_` 恰好等于 50（`avMID_CONSENSUS_TIME` 边界值）时，
原始代码从 `init`（50% 阈值）转入 `mid`（65% 阈值），变异后多停留一个评估周期在 `init`。
这意味着交易只需要 50% 而非 65% 的支持就可以通过。正常快速共识下完全无影响，只有当
当前轮时间恰好等于上一轮的一半时才触发。

---

### SC2. `DisputedTx::stalled()` 卡住检测边界

**文件:** `DisputedTx.h`（约第 340–350 行）

```cpp
// 原始逻辑:
if (weight > 80)
    return true;
if (weight < 20)
    return true;
return false;

// 变异:
if (weight >= 80)
    return true;
if (weight <= 20)
    return true;
return false;
```

**为什么微妙:** 使 weight=80 和 weight=20 也被判定为"已决定（stalled）"。
区别仅在权重恰好处于边界值（80 或 20）时。系统更倾向于宣布 stall，
可能导致过早进入 MovedOn 检测。

---

## 类别 SD — Close Time 共识

### SD1. `updateOurPositions()` Close Time 投票平局偏移

**文件:** `Consensus.h`（约第 1595 行）

```cpp
// 原始（close time 投票循环）:
if (v > threshVote)
{
    threshVote = v;
    closeTime = it.first;
}

// 变异:
if (v >= threshVote)
{
    threshVote = v;
    closeTime = it.first;
}
```

**为什么微妙:** `>` 变 `>=` 意味着两个 close time 票数相同时，"后遍历到的"胜出
（而非"先遍历到的"）。由于遍历顺序是 `std::map<NetClock::time_point, int>`
（按时间排序），这会偏向**更晚的** close time。通常不影响结果，但当恰好一半节点
投 T1、一半投 T2 时，平局打破方向变了，可能导致某个节点选择了与对等方不同的 close time，
阻止 close time 共识达成。

---

### SD2. `effCloseTime()` 移除 `+1s`

**文件:** `LedgerTiming.h`（约第 165 行）

```cpp
// 原始:
return std::max<time_point>(
    roundCloseTime(closeTime, resolution), (priorCloseTime + 1s));

// 变异:
return std::max<time_point>(
    roundCloseTime(closeTime, resolution), priorCloseTime);
```

**为什么微妙:** 移除 `+ 1s` 后允许有效 close time 等于前一个 close time。
绝大多数情况下 `roundCloseTime` 的返回值远大于 `priorCloseTime + 1s`，所以 `max`
照样选取 rounded 值。这个 bug 只在 close time 非常接近前一个 close time 时触发
（例如低延迟下的快速连续 ledger），导致两个 ledger 具有相同的 `effCloseTime`，
违反了 close time 严格单调递增的不变量。

---

## 类别 SE — LedgerTrie 与 Preferred Ledger

### SE1. `getPreferred()` 中的 `uncommitted == 0` 条件移除

**文件:** `LedgerTrie.h`（约第 780 行）

```cpp
// 原始（子节点选择逻辑）:
if ((margin > uncommitted) || (uncommitted == 0))
    return {};

// 变异:
if (margin > uncommitted)
    return {};
```

**为什么微妙:** `uncommitted == 0` 处理的是完全没有未提交支持的情况——即使最佳
子节点的 margin 大于零，当没有任何未提交的 validation 时算法应该停止向下遍历。
移除这个条件后，trie 遍历会在零未提交支持时继续深入，可能返回一个比正确分支点
更深的叶节点作为 preferred ledger。这只影响所有验证者都已提交到特定分支的情况
——正是健康网络中的正常状态。结果是 `getPreferred()` 可能返回 trie 深处的叶节点
而非正确的分支点。

---

### SE2. `getPreferred()` 中"preferred 的父节点"检查移除

**文件:** `Validations.h`（约第 887 行）

```cpp
// 原始:
if (preferred->seq == curr.seq() + Seq{1} &&
    preferred->ancestor(curr.seq()) == curr.id())
    return std::make_pair(curr.seq(), curr.id());

// 变异:
if (preferred->seq == curr.seq() + Seq{1})
    return std::make_pair(curr.seq(), curr.id());
```

**为什么微妙:** 原始："如果 preferred ledger 恰好比我们领先 1 **且**是我们的子孙，
则坚持当前 ledger。"变异："只要领先 1 就坚持当前。"这移除了祖先检查，因此即使
preferred ledger 在**另一个分叉**上但恰好领先 1 个 sequence，节点仍然坚持自己的
（错误的）ledger。这只在存在深度为 1 的分叉时才触发——非常罕见。正常线性链增长下
祖先检查总是满足的，所以 bug 不可见。

---

## 类别 SF — Validation 新鲜度与拜占庭检测

### SF1. `laggards()` 新鲜度比较方向

**文件:** `Validations.h`（约第 1138 行）

```cpp
// 原始:
if (adaptor_.now() <
        v.seenTime() + parms_.validationFRESHNESS &&
    trustedKeys.find(v.key()) != trustedKeys.end())

// 变异:
if (adaptor_.now() <=
        v.seenTime() + parms_.validationFRESHNESS &&
    trustedKeys.find(v.key()) != trustedKeys.end())
```

**为什么微妙:** `<` 变 `<=` 意味着恰好处于新鲜度边界（20 秒）的 validation 仍被
视为新鲜。这是一个 1 秒窗口的 bug：被视为"在线"的验证者集合在边界时刻多包含一个。
这可能阻止 `shouldPause()` 机制激活（因为 laggard 计数少了一个），导致共识在
不等待刚好超时的 lagging 节点的情况下继续推进。

---

### SF2. `Validations::add()` 序列替换窗口扩大（`&&` → `||`）

**文件:** `Validations.h`（约第 648 行）

```cpp
// 原始:
if (diff > parms_.validationCURRENT_WALL &&
    val.signTime() > seqit->second.signTime())
    seqit->second = val;

// 变异:
if (diff > parms_.validationCURRENT_WALL ||
    val.signTime() > seqit->second.signTime())
    seqit->second = val;
```

**为什么微妙:** `&&` 变 `||` 意味着满足任一条件就替换：要么时间差足够大，要么新的
signTime 更晚。原始要求同时满足两个条件。这使得冲突的 validation 更容易替换已跟踪的
记录，削弱了拜占庭检测。但因为替换只影响 `bySequence_` 映射（用于拜占庭检测，
不用于共识本身），bug 不会直接导致错误共识——只是让 `conflicting` 检测沉默，
使得拜占庭验证者不被察觉。

---

### SF3. `SeqEnforcer` 过期边界

**文件:** `Validations.h`（约第 120 行）

```cpp
// 原始:
if (now > (when_ + p.validationSET_EXPIRES))
    seq_ = Seq{0};
if (s <= seq_)
    return false;

// 变异:
if (now >= (when_ + p.validationSET_EXPIRES))
    seq_ = Seq{0};
if (s <= seq_)
    return false;
```

**为什么微妙:** 过期检查从"严格晚于"变为"等于或晚于"，SeqEnforcer 提前一个时钟
tick 重置，允许同一 sequence 的 validation 在恰好 10 分钟时被接受（而非被拒绝）。
窗口只有 1 秒，几乎不会在实际运行中触发。

---

## 类别 SG — shouldPause 与 Quorum 计算

### SG1. `shouldPause()` 离线计数边界

**文件:** `Consensus.h`（约第 1256 行）

```cpp
// 原始（phase 0 检查）:
if (laggards + offline > totalValidators - quorum)
    willPause = true;

// 变异:
if (laggards + offline >= totalValidators - quorum)
    willPause = true;
```

**为什么微妙:** 5 节点网络中 quorum = 4，totalValidators = 5，
`totalValidators - quorum = 1`。如果恰好 1 个验证者 lagging 或 offline，
原始：`1 > 1` → false（不暂停）；变异：`1 >= 1` → true（暂停）。
系统变得更保守，在不需要暂停时也暂停，导致一个 ledger close 延迟。
只有当恰好有 `totalValidators - quorum` 个验证者离线时才可见。

---

### SG2. `calculateQuorum()` 浮点精度（`0.8f` → `0.8`）

**文件:** `ValidatorList.cpp`（quorum 计算）

```cpp
// 原始:
return static_cast<std::size_t>(std::ceil(effectiveUnlSize * 0.8f));

// 变异:
return static_cast<std::size_t>(std::ceil(effectiveUnlSize * 0.8));
```

**为什么微妙:** 把 `0.8f`（float）改为 `0.8`（double）。由于 IEEE 754 浮点表示，
`5 * 0.8f` 和 `5 * 0.8` 在 ULP 层面不同。实际中 `0.8f` = `0.800000011920928955...`，
所以 `5 * 0.8f = 4.00000005...` → `ceil = 5`；而 `0.8`（double）= 精确的 0.8，
所以 `5 * 0.8 = 4.0` → `ceil = 4`。这意味着**对于 5 个验证者，quorum 从 5 变为 4**。
只改了一个字符（去掉 `f`），效果却是 quorum 减一，使共识更容易达成。
效果取决于 UNL 大小。

---

## 类别 SH — 提案与 Ledger 接受

### SH1. `onClose()` 中 `parentHash` → `hash`

**文件:** `RCLConsensus.cpp`（约第 397 行）

```cpp
// 原始:
prevLedger->info().parentHash

// 变异:
prevLedger->info().hash
```

**为什么微妙:** Proposal 的 "prevLedger" 字段使用的是 `parentHash`（正在构建的
ledger 的祖父），而非直接父级的 hash。这是因为 peer 通过比较 proposal 的 prevLedger
来判断是否在同一轮工作。改为 `hash` 后，本节点的 proposal 看起来引用了不同的
"previous ledger"。但在很多情况下 peer 会检测到不匹配并切换到 wrongLedger 模式
进行自我纠正，所以 bug 只在快速 ledger 推进、不匹配未及时被检测到时才造成问题。

---

### SH2. `validate()` 中移除 `!consensusFail` 守卫

**文件:** `RCLConsensus.cpp`（约第 590 行）

```cpp
// 原始:
if (validating_ && !consensusFail &&
    app_.getValidations().canValidateSeq(built.seq()))

// 变异:
if (validating_ &&
    app_.getValidations().canValidateSeq(built.seq()))
```

**为什么微妙:** 移除 `!consensusFail` 守卫。正常运行时 `consensusFail` 为 false，
守卫无实际作用。Bug 只在共识实际失败时触发（state = `MovedOn`，很罕见）。
触发时，节点会为一个可能分歧的 ledger 发送 validation，误导 peer 认为网络已达成共识。
这是一个"把共识失败伪装成成功"的危险安全漏洞。

---

### SH3. `checkAccept()` quorum 比较边界

**文件:** `LedgerMaster.cpp`（在 `checkAccept` 中）

```cpp
// 原始:
if (validations >= quorum())

// 变异:
if (validations > quorum())
```

**为什么微妙:** `>=` 变 `>` 意味着节点需要比 quorum 多一个 validation 才接受 ledger。
quorum = 4 时需要 5 而非 4。节点接受已验证 ledger 的速度变慢，正常条件下只是轻微延迟。
但如果恰好只有 quorum 个验证者发了 validation（满足最低要求），这个节点永远不接受，
可能落后于网络。当超过 quorum 个验证者验证时（常见情况），bug 完全不可见。

---

## 微妙 Bug 汇总表

| 编号 | 文件 | 变异内容 | 触发条件 | 检测难度 |
|------|------|----------|----------|----------|
| SA1 | Consensus.h | 取整 `+1` | 特定 UNL 大小 | ★★★★☆ |
| SA2 | Consensus.cpp | `>=` → `>` | 恰好 80% 同意 | ★★★☆☆ |
| SA3 | DisputedTx.h | 分母 `+1` → `+2` | 少量投票接近阈值 | ★★★★☆ |
| SA4 | Consensus.h | 分母 `+1` 偏移 | 慢轮次接近边界 | ★★★★★ |
| SB1 | Consensus.cpp | `>` → `>=` 关闭条件 | 偶数前轮提议者 | ★★★☆☆ |
| SB2 | Consensus.cpp | 多加 `&& > 0` 守卫 | 零提议者边界 | ★★★★★ |
| SB3 | LedgerTiming.h | `==` → `!=` 取模 | close time 分歧 | ★★★★☆ |
| SB4 | Validations.h | `>` → `>=` signTime | 同秒 validation | ★★★★★ |
| SC1 | ConsensusParms.h | `<` → `<=` 中间状态 | 半程时间边界 | ★★★★☆ |
| SC2 | DisputedTx.h | `>` → `>=` stalled | 权重恰在边界 | ★★★★☆ |
| SD1 | Consensus.h | `>` → `>=` 投票平局 | 票数相等 | ★★★★☆ |
| SD2 | LedgerTiming.h | 移除 `+1s` | 快速连续 ledger | ★★★☆☆ |
| SE1 | LedgerTrie.h | 移除 `uncommitted==0` | 全部已提交 | ★★★★★ |
| SE2 | Validations.h | 移除祖先检查 | 深度为 1 的分叉 | ★★★★☆ |
| SF1 | Validations.h | `<` → `<=` 新鲜度 | 恰好 20 秒边界 | ★★★★★ |
| SF2 | Validations.h | `&&` → `\|\|` 替换 | 拜占庭检测 | ★★★★★ |
| SF3 | Validations.h | `>` → `>=` 过期 | 恰好 10 分钟边界 | ★★★★★ |
| SG1 | Consensus.h | `>` → `>=` 暂停检查 | 恰好 quorum-1 离线 | ★★★★☆ |
| SG2 | ValidatorList.cpp | `0.8f` → `0.8` | 特定 UNL 大小（如 5） | ★★★★★ |
| SH1 | RCLConsensus.cpp | parentHash → hash | 快速 ledger 推进 | ★★★★☆ |
| SH2 | RCLConsensus.cpp | 移除 `!consensusFail` | 共识失败 | ★★★☆☆ |
| SH3 | LedgerMaster.cpp | `>=` → `>` 接受 | 恰好 quorum 个 validation | ★★★☆☆ |

**检测难度**表示常规（非进化）测试检测到该 bug 的难度。★★★★★ = 几乎不可能，需要精确的时序条件。

---

## 微妙 Bug 推荐优先级（for evotest）

1. **SG2**（`0.8f` → `0.8` quorum 浮点精度）— 只改一个字符，UNL=5 时 quorum 从 5 变 4
2. **SA2**（共识 `>=` → `>`）— 经典 off-by-one，spec_checker 可检测
3. **SE1**（LedgerTrie `uncommitted==0` 移除）— 深层算法 bug
4. **SD1**（close time 投票平局偏移）— 时序相关，难检测
5. **SF2**（拜占庭检测 `&&` → `||`）— 削弱安全性，happy path 不可见
6. **SA3**（DisputedTx 分母偏移）— 改变交易包含偏向
7. **SB3**（时间分辨率永不变粗）— 多轮级联效应
8. **SH2**（共识失败时仍发 validation）— 罕见但危险的安全违规
