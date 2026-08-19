# AnduinOS / Ubuntu 双仓库发布操作手册

本文档用于在一台个人专线 AnduinOS 或 Ubuntu 电脑上管理源码，并同时推送到 GitHub 和 Aiursoft GitLab。

适用环境：

```text
AnduinOS / Ubuntu
Git 2.53.0
个人或明确授权使用的专线设备
```

本文中的占位符必须替换为真实值：

```text
<EMAIL>                    提交邮箱
<NAME>                     提交者姓名
<GITHUB_USER>              GitHub 用户名
<AIURSOFT_GITLAB_HOST>     Aiursoft GitLab 的准确域名
<AIURSOFT_NAMESPACE>       GitLab 用户名或群组路径
```

## 1. 推荐的设备分工

```text
lab Windows        仅用于兼容性测试和生成允许转出的源码包
个人专线设备        保存主仓库、SSH 私钥、提交历史和发布凭据
AnduinOS / Ubuntu  运行、测试和发布
```

不要在 lab Windows 上登录个人 GitHub/GitLab，不要把专线设备的 SSH 私钥复制回 lab。

## 2. 代码应该放在哪里

如果 `/data` 是个人设备上的持久化数据盘，并且不是多人共享目录，推荐：

```text
/data/<你的Linux用户名>/projects/task-manager-og-linux
```

先检查 `/data`：

```bash
findmnt -T /data
df -hT /data
ls -ld /data
```

确认它是预期的数据盘、空间充足并允许存放个人源码后，创建目录：

```bash
sudo install -d -o "$USER" -g "$(id -gn)" -m 0700 "/data/$USER"
install -d -m 0750 "/data/$USER/projects"
install -d -m 0700 "/data/$USER/incoming"
```

不要使用 `sudo git`，Git 仓库和 SSH 密钥都应属于普通用户。

如果 `/data` 是共享盘、临时盘、未加密盘，或者用途不明确，改用：

```text
$HOME/projects/task-manager-og-linux
```

对应命令：

```bash
install -d -m 0750 "$HOME/projects"
install -d -m 0700 "$HOME/incoming"
```

## 3. 转入源码

建议转移源码包，而不是复制 lab 机器上的 Git 凭据或用户配置。转移行为本身必须符合 lab 的数据转出规定。

把源码包放入专线设备的 incoming 目录，然后验证发布方提供的 SHA-256：

```bash
cd "/data/$USER/incoming"
sha256sum tmog-linux-beta06-source-transfer.zip
```

校验值一致后解压。Python 标准库即可处理 ZIP：

```bash
python3 -m zipfile -e \
  tmog-linux-beta06-source-transfer.zip \
  "/data/$USER/projects"

cd "/data/$USER/projects/task-manager-og-linux"
```

如果决定使用 HOME 目录，把上面的 `/data/$USER` 换成 `$HOME`。

确认目录中没有 Git 历史和密钥：

```bash
test ! -d .git && echo "No Git history: OK"
find . -maxdepth 2 -type f | sort
```

## 4. 配置 Git 身份

只在个人专线设备上配置：

```bash
git config --global init.defaultBranch main
git config --global user.name "<NAME>"
git config --global user.email "<EMAIL>"
git config --global core.autocrlf input

git config --global --list
```

邮箱可以使用 GitHub 提供的 noreply 地址。提交邮箱与登录邮箱不必完全相同。

## 5. 理解密钥、指纹和 API Token

这三项不是同一个东西：

| 项目 | 用途 | 本手册是否需要 |
| --- | --- | --- |
| SSH 私钥/公钥 | 证明这台设备有权推送 | 需要 |
| 服务器主机指纹 | 确认连接的确是目标服务器 | 需要核验 |
| API Token / PAT | HTTPS 推送或自动调用 API | 普通 SSH 推送不需要 |

因此第一次发布可以完全不创建 API key，使用 SSH 即可。

## 6. 为两个平台分别生成 SSH 密钥

创建受保护的 SSH 目录：

```bash
install -d -m 0700 "$HOME/.ssh"
```

GitHub 使用一把独立密钥：

```bash
ssh-keygen -t ed25519 -a 64 \
  -f "$HOME/.ssh/id_ed25519_github_publish" \
  -C "<EMAIL> GitHub publishing"
```

Aiursoft GitLab 使用另一把独立密钥：

```bash
ssh-keygen -t ed25519 -a 64 \
  -f "$HOME/.ssh/id_ed25519_aiursoft_publish" \
  -C "<EMAIL> Aiursoft GitLab publishing"
```

为两把私钥设置不同且可靠的 passphrase。以下文件绝不能上传或发送：

```text
~/.ssh/id_ed25519_github_publish
~/.ssh/id_ed25519_aiursoft_publish
```

只有以 `.pub` 结尾的文件可以登记到网站。

GitHub 页面要求的是你自己的公钥文件中的完整一行，例如：

```bash
cat "$HOME/.ssh/id_ed25519_github_publish.pub"
```

格式应以 `ssh-ed25519` 开头。服务器指纹 `SHA256:...`、`ssh-keyscan` 输出和私钥内容都不能粘贴到 GitHub 的 `SSH Keys` 输入框。

## 7. 核验服务器主机指纹

### GitHub

读取连接端返回的 Ed25519 指纹：

```bash
ssh-keyscan -t ed25519 github.com 2>/dev/null | ssh-keygen -lf -
```

应与 GitHub 官方文档当前公布的 Ed25519 指纹一致：

```text
SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU
```

官方核验地址：

```text
https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints
```

一致后才写入 `known_hosts`：

```bash
ssh-keyscan -H -t ed25519 github.com 2>/dev/null >> "$HOME/.ssh/known_hosts"
chmod 0600 "$HOME/.ssh/known_hosts"
```

### Aiursoft GitLab

先从 Aiursoft GitLab 管理员、内部文档或可信专线渠道取得：

```text
准确域名
SSH 端口
Ed25519 主机指纹
```

不要根据名称猜测域名，也不要未经核对就接受首次连接提示。

假设 SSH 使用默认 22 端口：

```bash
ssh-keyscan -t ed25519 <AIURSOFT_GITLAB_HOST> 2>/dev/null | ssh-keygen -lf -
```

输出与管理员提供的指纹完全一致后，再执行：

```bash
ssh-keyscan -H -t ed25519 <AIURSOFT_GITLAB_HOST> 2>/dev/null >> "$HOME/.ssh/known_hosts"
chmod 0600 "$HOME/.ssh/known_hosts"
```

如果使用非 22 端口，`-p` 必须写在主机名之前。例如 Aiursoft GitLab 使用 2202 端口时：

```bash
ssh-keyscan -p 2202 -t ed25519 gitlab.aiursoft.com 2>/dev/null | ssh-keygen -lf -
```

下面这种参数顺序是错误的：

```bash
ssh-keyscan -t ed25519 gitlab.aiursoft.com -p 2202
```

如果正确命令仍显示 `(stdin) is not a public key file`，表示 `ssh-keyscan` 没有取得任何主机公钥。先直接检查服务器返回：

```bash
ssh-keyscan -p 2202 ssh.aiursoft.com
```

完全没有输出时，检查专线连通性、域名、端口和防火墙；有输出但没有 `ssh-ed25519` 时，需要向管理员确认该服务器实际启用的主机密钥类型和官方指纹。

后面的 SSH 配置也必须增加端口：

```sshconfig
Host aiursoft-gitlab
    HostName gitlab.aiursoft.com
    Port 2202
    User git
    IdentityFile ~/.ssh/id_ed25519_aiursoft_publish
    IdentitiesOnly yes
    StrictHostKeyChecking yes
```

## 8. 配置两个 SSH 主机别名

编辑 `$HOME/.ssh/config`：
`nano ~/.ssh/config `

```sshconfig
Host github-publish
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_ed25519_github_publish
    IdentitiesOnly yes
    StrictHostKeyChecking yes

Host aiursoft-gitlab
    HostName <AIURSOFT_GITLAB_HOST>
    User git
    IdentityFile ~/.ssh/id_ed25519_aiursoft_publish
    IdentitiesOnly yes
    StrictHostKeyChecking yes
```

设置权限：

```bash
chmod 0600 "$HOME/.ssh/config"
chmod 0600 "$HOME/.ssh/id_ed25519_github_publish"
chmod 0600 "$HOME/.ssh/id_ed25519_aiursoft_publish"
chmod 0644 "$HOME/.ssh/id_ed25519_github_publish.pub"
chmod 0644 "$HOME/.ssh/id_ed25519_aiursoft_publish.pub"
```


## 9. 把公钥登记到网站

显示 GitHub 公钥：

```bash
cat "$HOME/.ssh/id_ed25519_github_publish.pub"
```

登录 GitHub，进入：

```text
Settings > SSH and GPG keys > New SSH key
```

显示 Aiursoft GitLab 公钥：

```bash
cat "$HOME/.ssh/id_ed25519_aiursoft_publish.pub"
```

登录 Aiursoft GitLab，进入用户设置中的 `SSH Keys`，登记该公钥。

只复制一整行 `.pub` 内容。不要复制私钥。

## 10. 测试 SSH 认证

```bash
ssh -T github-publish
ssh -T aiursoft-gitlab
```

GitHub 正常情况下会说明认证成功但不提供 shell，这不是错误。GitLab 正常情况下会显示欢迎信息。

如果出现新的主机指纹提示，先停止，不要直接输入 `yes`；重新执行第 7 节的核验。

## 11. 在网站上创建两个空仓库

在两个平台分别创建：

```text
task-manager-og-linux
```

不要自动创建 README、LICENSE 或 `.gitignore`，本地已经包含这些文件。

在 Aiursoft GitLab 中确认仓库所属路径是你的用户空间还是指定群组，并记下完整 namespace。

## 12. 首次提交前检查版权信息

当前项目是独立实现，采用 MIT License。首次提交前在专线设备上检查：

```bash
sed -n '1,20p' LICENSE
sed -n '1,40p' README.md
```

确认 `LICENSE` 中的版权主体符合你的实际安排。不要把原版 TMOG 的源码、图标、二进制文件或官方截图放入仓库。

## 13. 初始化并创建第一次提交

```bash
cd "/data/$USER/projects/task-manager-og-linux"

git init
git branch -M main
git add .
```

确保 Ubuntu 脚本具有 Git 可执行权限：

```bash
git update-index --chmod=+x run.sh install.sh uninstall.sh
git ls-files --stage '*.sh'
```

三个脚本前面应显示 `100755`。

提交前检查：

```bash
git status
git diff --cached --check
git diff --cached --stat
```

不应出现下面这些内容：

```text
__pycache__/
screenshots/
*.zip
.ssh/
API Token 或私钥
```

创建提交：

```bash
git commit -m "Initial release: TMOG Linux beta06"
```

## 14. 添加两个远程仓库

GitHub：

```bash
git remote add github \
  git@github-publish:<GITHUB_USER>/task-manager-og-linux.git
```

Aiursoft GitLab：

```bash
git remote add aiursoft \
  git@aiursoft-gitlab:rdf/task-manager-og-linux.git
```

检查地址：

```bash
git remote -v
```

## 15. 第一次推送

先推 GitHub，并把它设为默认上游：

```bash
git push -u github main
```

再推 Aiursoft GitLab：

```bash
git push aiursoft main
```

分别打开两个仓库网页，确认文件列表和最新提交 ID 一致。

## 16. 创建 beta06 标签

```bash
git tag -a v0.6.0 -m "TMOG Linux beta06"
git push github v0.6.0
git push aiursoft v0.6.0
```

安装 ZIP 应作为 GitHub/GitLab Release 附件上传，不要提交到源码历史。

## 17. 后续日常推送

```bash
cd "/data/$USER/projects/task-manager-og-linux"

git status
git add .
git diff --cached
git commit -m "说明本次修改"

git push github main
git push aiursoft main
```

## 18. 可选：配置签名提交

SSH 推送认证与提交签名可以使用不同密钥。需要 Verified 提交时，建议再生成一把签名密钥：

```bash
ssh-keygen -t ed25519 -a 64 \
  -f "$HOME/.ssh/id_ed25519_git_signing" \
  -C "<EMAIL> Git commit signing"

git config --global gpg.format ssh
git config --global user.signingkey "$HOME/.ssh/id_ed25519_git_signing.pub"
git config --global commit.gpgsign true
git config --global tag.gpgsign true
```

把签名公钥分别登记为两个平台支持的 Signing key。平台未确认支持前，不要删除未签名提交，也不要强制改写历史。

## 19. API Token 什么时候才需要

以下操作使用 SSH 时不需要 API Token：

```text
clone
fetch
pull
push
推送标签
```

只有以后编写自动发布脚本、调用 GitHub/GitLab API 或使用 HTTPS Git 时，才考虑创建最小权限、有限期限的 Token。Token 只保存在专线设备的密码管理器或受保护的 CI Secret 中，不能写进仓库、shell 历史或操作手册。

## 20. 最终安全检查

```bash
git status
git remote -v
git log --oneline --decorate -5
git ls-files | sort
```

确认：

- 工作区没有意外文件。
- 两个远程地址均正确。
- 私钥不在仓库中。
- GitHub 与 Aiursoft GitLab 的主机指纹均已通过可信渠道核验。
- `/data` 位于个人可控、持久化并有备份的数据盘。
