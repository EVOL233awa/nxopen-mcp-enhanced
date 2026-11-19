# 使用現成索引串接 nxopen-mcp-enhanced 完整指南

[English](setup-prebuilt-index.md) | **繁體中文**

> 適用情境:你拿到了一份同事建好的 `index.db`(約 500 MB),想在自己的
> 電腦上讓 Claude Code / Codex / Cursor 查詢 NXOpen API,**不需要**自己
> 花數小時建索引。
>
> ⚠️ 授權提醒:索引內含 Siemens API 文件內容,僅限**組織內有 NX 授權**
> 的人員使用,請勿外流或公開散布。

---

## 0. 你需要準備的東西

| 項目 | 說明 |
|------|------|
| Windows 電腦 | macOS/Linux 也可,路徑自行對應 |
| Python 3.11 或更新 | 檢查:`python --version`;沒有就到 https://www.python.org/downloads/ 安裝,**安裝時勾選 "Add python.exe to PATH"** |
| 磁碟空間約 0.5 GB | 索引本身;只有走本地 BGE-M3 路線才再加約 2 GB 模型 |
| `index.db` 檔案 | 同事給你的,約 500 MB |
| 嵌入後端 | 硅基流動免費的 `BAAI/bge-m3` + `BAAI/bge-reranker-v2-m3`(建議,不下載任何模型)或本地 `[embed]` |
| Claude Code(或 Codex / Cursor) | 任一支援 MCP 的 AI 編碼工具 |

---

## 1. 安裝 nxopen-mcp-enhanced

開啟「命令提示字元」或 PowerShell:

```bash
pip install nxopen-mcp-enhanced
```

- 用現成索引**不需要** `[reflect]`(繼承鏈已包含在索引中)
- 語意搜尋需要的是嵌入後端,不是 PyTorch:建議用硅基流動的免費模型,不必裝
  `[embed]`、也不下載 2 GB 模型。要改用本地模型才裝
  `pip install "nxopen-mcp-enhanced[embed]"`

安裝完驗證:

```bash
nxopen-mcp-enhanced --help
```

看到 `index` / `serve` 兩個指令即成功。若顯示「不是內部或外部命令」,
表示 Python 的 Scripts 目錄不在 PATH——最快的解法是改用完整路徑,
先找出位置:

```bash
python -c "import sysconfig; print(sysconfig.get_path('scripts'))"
```

之後所有指令中的 `nxopen-mcp-enhanced` 都改成 `<那個路徑>\nxopen-mcp-enhanced.exe`。

---

## 2. 放置索引檔

把拿到的 `index.db` 複製到預設位置:

```
C:\Users\<你的帳號>\.nxopen-mcp-enhanced\index.db
```

`.nxopen-mcp-enhanced` 資料夾不存在就自己建一個。用 PowerShell 一行完成:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.nxopen-mcp-enhanced" | Out-Null
Copy-Item "D:\下載\index.db" "$env:USERPROFILE\.nxopen-mcp-enhanced\index.db"
```

> 不想放預設位置?也可以放任何地方,後面註冊時加
> `--db "D:\你的路徑\index.db"` 即可。

---

## 3. 註冊到 Claude Code

### 方法 A:CLI 一行(建議)

```bash
claude mcp add -s user nxopen -- nxopen-mcp-enhanced serve
```

- `-s user`:所有專案都能用,不限單一資料夾
- 索引不在預設位置時:`claude mcp add -s user nxopen -- nxopen-mcp-enhanced serve --db "D:\路徑\index.db"`

### 方法 B:找不到 `claude` 指令時,直接編設定檔

開啟 `C:\Users\<你的帳號>\.claude.json`,在最外層加入(或併入既有的)
`mcpServers` 區塊:

```json
{
  "mcpServers": {
    "nxopen": {
      "type": "stdio",
      "command": "nxopen-mcp-enhanced",
      "args": ["serve"]
    }
  }
}
```

`nxopen-mcp-enhanced` 不在 PATH 時,`command` 填完整路徑,例如
`C:\\Python312\\Scripts\\nxopen-mcp-enhanced.exe`(JSON 中反斜線要寫兩個)。

---

## 4. 驗證串接

1. **開一個全新的 Claude Code session**(MCP 只在啟動時連線,舊視窗
   不會自動接上)
2. 輸入 `/mcp` → 應顯示 `nxopen ✓ connected`
3. 先測**精確查詢**(不需模型,應該秒回):

   > 用 nxopen 查 CavityMillingBuilder 有哪些成員

4. 再測**語意查詢**:

   > 用 nxopen 搜尋「如何設定主軸轉速」

   走遠端嵌入服務(建議的硅基流動設定)時,這一步約 1 秒回覆。走**本地**路線則是:
   ⏳ **第一次語意查詢會停 1–3 分鐘**:先下載 BGE-M3 模型(約 2 GB,
   僅此一次),再載入記憶體。之後同一個 session 內都是秒回。
   **這不是當機,請不要中斷它。**

全部通過就完成了。之後正常使用即可,例如:

> 幫我寫一個建立鑽孔操作並設定進給率的 NXOpen C# 程式

Claude 會自動呼叫 nxopen 的工具查真實 API 再寫程式。

---

## 4b. 改用遠端嵌入(不下載模型)

本地模型是選配。硅基流動把 `BAAI/bge-m3` 與 `BAAI/bge-reranker-v2-m3` 標為免費模型,
正是本 server 的預設組合,所以檢索行為不變、也不必下載任何東西。啟動 server 前設好這幾
個環境變數(寫進 MCP 設定的 `env` 區塊,讓 client 傳給 server):

| 變數 | 值 |
|---|---|
| `NXOPEN_MCP_EMBEDDER` | `remote` |
| `NXOPEN_MCP_EMBED_URL` | `https://api.siliconflow.cn` |
| `NXOPEN_MCP_EMBED_MODEL` | `BAAI/bge-m3` |
| `NXOPEN_MCP_EMBED_API_KEY` | 你的硅基流動 API key |
| `NXOPEN_MCP_RERANK` | `1` |
| `NXOPEN_MCP_RERANK_URL` | `https://api.siliconflow.cn/v1/rerank` |
| `NXOPEN_MCP_RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` |
| `NXOPEN_MCP_RERANK_API_KEY` | 同一把 key |

拿到的索引照樣可用:免費模型就是本專案建索引時用的同一組權重。完整行為表見
主 [README](../README.zh-CN.md#远程嵌入与重排推荐)。

---

## 5. Codex / Cursor 串接(可選)

**Cursor**:在 `mcp.json`(專案 `.cursor/mcp.json` 或全域設定)加入與
上方方法 B 相同的 JSON 區塊。

**Codex CLI**:編輯 `~/.codex/config.toml`:

```toml
[mcp_servers.nxopen]
command = "nxopen-mcp-enhanced"
args = ["serve"]
```

---

## 6. 疑難排解

| 症狀 | 原因與解法 |
|------|-----------|
| `/mcp` 顯示 not connected | 舊 session 不會自動連線 → 開新 session 或重啟工具 |
| `error: index not found at ...` | 索引不在預設位置 → 確認第 2 步的路徑,或註冊時加 `--db` |
| 第一次搜尋「卡住」幾分鐘 | 只有本地路線會這樣:一次性下載並載入 BGE-M3 模型,等它完成;或改走遠端(第 4b 步) |
| 模型下載失敗(公司網路) | 需要能連 huggingface.co;有 proxy 時先設 `HTTPS_PROXY`,或改走遠端(第 4b 步),完全不下載 |
| `nxopen-mcp-enhanced` 不是內部或外部命令 | Scripts 目錄不在 PATH → 見第 1 步,改用完整路徑 |
| 精確查詢很快、語意查詢每次都慢 | 本地路線:模型只在 server 存活期間常駐;重啟 session 後第一次語意查詢會重新載入(約 1 分鐘,不會重新下載)。想隱藏這段用 `--preload`,或改走遠端 |
| 搜尋回報嵌入服務錯誤 | 後端不可達 → 檢查 API key 與網路;仍可用 `get_class` / `get_member` 走精確查詢,它們完全不碰嵌入服務 |
| 想確認索引內容 | 索引是 SQLite 檔,`members` 表約 9.8 萬筆即為完整 NX12 文件 |

---

## 7. 之後的維護

- **升級軟體**:`pip install -U nxopen-mcp-enhanced`(走本地模型時加 `[embed]`;索引不受影響)
- **換 NX 版本的索引**:拿到新的 `index.db` 直接覆蓋同一路徑即可,
  不用重新註冊
- **自己建索引**(有 NX 安裝時):見主 [README](../README.zh-CN.md)
  的「快速開始」

有問題請洽提供索引檔的同事,或到
https://github.com/mingfeng6684/nxopen-mcp/issues 回報。
