# DATA_NOTES

## 数据范围

管线聚合三类数据:

1. 矿业新闻: RSS 入口为 Mining.com，可扩展 S&P Global Mining RSS 或其他行业新闻源。
2. 关键矿产政策: 中国稀土集团官网、澳洲 DISR 关键矿产相关页面。
3. 价格: LME 铜/锌/镍、SHFE 锂相关公开页面、上海钢联铁矿石相关公开页面。

默认目标是近 30 天每类至少 200 条，合计不少于 600 条。真实公开源可能存在登录墙、频控、RSS 数量不足或页面结构变化；当真实抓取不足时，管线会生成带 `is_synthetic=true` 的补齐样本，用于开发、接口联调和评测基线。生产环境应禁用补齐样本，或替换为可授权访问的数据接口。

## SQLite 表

### documents

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT PRIMARY KEY | 稳定主键，来自 canonical URL 或规范化内容哈希 |
| `source_type` | TEXT | `news`、`policy`、`price` |
| `source_name` | TEXT | 数据源名称，例如 `Mining.com RSS` |
| `url` | TEXT | 原始链接 |
| `title` | TEXT | 标题 |
| `published_at` | TEXT | ISO 8601 发布时间 |
| `summary` | TEXT | 摘要或抓取正文摘要 |
| `content` | TEXT | 清洗后的正文 |
| `metadata` | TEXT | JSON 字符串，保存国家、商品、指标、是否 synthetic 等扩展字段 |
| `content_hash` | TEXT | 规范化文本哈希 |
| `embedding` | TEXT | JSON 数组，本地哈希向量 |
| `created_at` | TEXT | 入库时间 |

## 主键策略

优先使用规范化后的 URL 生成主键:

```text
sha256(source_type + "|" + normalized_url)
```

如果缺少 URL，则使用标题、日期和正文片段:

```text
sha256(source_type + "|" + title + "|" + published_at + "|" + normalized_content[:512])
```

## 去重策略

去重分两层:

1. 完全去重: `content_hash` 相同直接丢弃。
2. 近似去重: 标题 Jaccard 相似度大于等于 `0.9` 且发布时间相差不超过 2 天时保留较长正文版本。

该策略能处理 RSS 摘要、转载和同源分页造成的重复。价格数据按 `source_type + source_name + commodity + published_at` 更偏事件化处理，避免同一天不同品种被误合并。

## 向量策略

当前实现使用本地、确定性的哈希词向量，便于无外部 API 环境运行:

- 中文按 2-gram/3-gram 字符片段切分
- 英文按单词切分
- token 经 sha256 映射到固定维度
- 使用 L2 归一化后做 cosine similarity

生产环境可替换为 OpenAI embeddings、BGE/M3E、本地 sentence-transformers、Chroma、Qdrant、Milvus 或 pgvector。接口层不依赖具体向量实现。
