# 06: 她的手写签名

**What to build:** 信末是她的手写签名，从左到右写出来。はづき没有签名图，信末用信上的字体写她的名字。

见 spec「签名」。

**Blocked by:** 01

**Status:** done

- [x] 旧版 28 张签名图（CDN `stand.hmhnk.top` 的 `letters/signatures/` 下，文件名带哈希；对照 `last-letter` 分支 `letters.json` 里的 `signature_image` 找）下载回仓库的 `characters/signatures/`，按角色 id 命名。
- [x] `characters.toml` 每位加一个可选的签名字段；角色接口带签名图地址（没有时为空）。
- [x] 照头像的写法提供签名图接口（带 ETag，304）。
- [x] 读一封带签名图地址或替代文字（她的名字）；前端信末有图时从左到右显出（旧版的 `sign` 动效，1.6 秒），没有图时照字写。
- [x] 后端测试照头像接口的测试；角色加载测试覆盖签名字段可选。

## Comments

### 票 01 交接

- 读一封的 `signature` 已经是 `{"image": null, "text": 她的名字}`，前端 `LetterLayer` 的 `Signature` 有图时用图（`letter-signature` 三行高、`animate-sign`），取不到时退回照字写。后端只要填 `image`。

### 实现说明（票 06）

- **签名图**：旧版 28 张 webp 按 `letters.json` 的 `signature_image` 下载到 `characters/signatures/<id>.webp`（共约 750 KB），内容哈希和 CDN 文件名里的一致；はづき没有。`characters.toml` 里这 28 位各加 `signature = "signatures/<id>.webp"`，文件头注释说明了这个字段；`docs/configuration*.md` 三语各加一行。
- **后端**：`Character.signature`（可选文件，照 `avatar` 用 `_optional_file` 读，缺文件时警告、当没有）。`characters.signature_url(character)` 给出 `/api/characters/<id>/signature` 或 None，角色列表的 `signature_url` 和读一封的 `signature.image` 都用它；`Letter` 多一个 `signature_url`，在 `Letters.letter` 里和名字一起填。新接口 `GET /api/characters/{id}/signature` 走 `_picture`（ETag、304、缓存一天），不要登录。
- **判断**：Python 3.11 的 `mimetypes` 不认识 `.webp`（3.13 才加），镜像里没有 `/etc/mime.types` 时也一样，签名图原本会以 `application/octet-stream` 发出；`_picture` 按后缀显式给 `image/webp`，测试断言了类型。前端 `Character` 类型没加 `signature_url`：信末用的是读一封里的 `signature.image`，前端用不到。
- **前端**：不用改。票 01 的 `Signature` 和 `animate-sign`（1.6 秒，`clip-path` 从左到右）和旧版一致。
- **验收**：本地构建版上用 Playwright 看了电脑和手机：真乃、めぐる的签名图加载成功并从左到右显出（中途截图只露出前两个字），はづき照字写她的名字。截图看过，没留存；验收用户已删。
- **审查**：按 `CODING_STANDARDS.md`「Tests」删掉三条和已有测试走同一路径的测试；`Letter` 的字段从 `signature` 改名为 `signature_url`，免得和装名字的 `signed` 混。保留：缓存参数化里的 `signature` 一行（唯一证明这个接口走了 `_picture` 的断言）；路由路径写在 `characters.signature_url` 里（`letters.py` 也自己拼语音地址）。
