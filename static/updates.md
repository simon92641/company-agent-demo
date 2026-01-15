## 2026-01-07
- [x] 完成中英切换与抽屉式帮助
- [ ] 增量爬取：按 URL 哈希跳过未变内容
- [x] 重新制定爬取策略：qlik公司，blog太多，有效信息少，污染数据
- [ ] 分块策略：保持段落完整 & 标题+正文拼接

## 2026-01-10
- [x] Playwright JS 兜底抓取接入（仅对必要页面启用）
- [x] 多语言过滤：只保留 zh / en
## 2026-01-12
- [x] 增大TopK检索数量到8，重建faq，更精准
- [ ] 1.切块优先句子，2.爬虫过滤掉转换页，3.“联系”就只该检索：/contact /support /offices /global-offices /help“公司做什么”就只该检索：/company /about /products /platform /solutions 结论：缺少“问题路由（routing）+ 质量门禁（guardrail）”。