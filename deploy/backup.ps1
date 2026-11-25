# Скрипты бэкапов vibe-chat (PostgreSQL + Silo + Keycloak realm)
#
# Что бэкапим (§13 концепции — всё состояние в этих трёх местах):
#   1. PostgreSQL  — пользователи, чаты, сообщения, файлы-метаданные (volume pgdata)
#   2. Silo        — объекты файлов в бакете vibe-files (volume silodata)
#   3. realm-export.json + server.env — конфигурация (обычные файлы в deploy/)
#
# Keycloak (учётки, realm vibe-chat) живёт в собственной БД Keycloak? — НЕТ:
#   в этой сборке KC работает со встроенным H2 (start-dev, без спифа на внешний PG),
#   пароли пользователей создаются через Admin API при регистрации.
#   → Бэкапим экспорт realm'а + следим, что регистрация восстанавливаема
#     (KC-аккаунты пересоздаются бэкендом при регистрации; существующие
#      пользователи после потери KC-БД смогут войти только после повторной
#      синхронизации — приемлемо для MVP, см. «Ограничение» внизу).
#
# Куда складывать: ./backups/<дата>/ внутри репозитория или любой внешний путь,
# передаваемый первым аргументом (по умолчанию ./backups).
#
# Восстановление (restore):
#   1. docker compose -f deploy/docker-compose.server.yml --env-file deploy/server.env up -d postgres silo
#   2. gunzip -c <backup>/postgres.sql.gz | docker compose -f deploy/docker-compose.server.yml exec -T postgres psql -U vibe -d vibe
#      (mc mirror --overwrite <backup>/silo/ локально → целевой бакет vibe-files)
#   3. realm-export.json и server.env — вернуть на место, перезапустить стек

param(
    [string]$Dest = "./backups",
    [switch]$Restore   # не реализовано в MVP — см. восстановление вручную выше
)

$ErrorActionPreference = "Stop"
$Compose = "docker compose -f deploy/docker-compose.server.yml --env-file deploy/server.env"

$stamp = Get-Date -Format "yyyy-MM-dd_HH-mm"
$dir = Join-Path $Dest $stamp
New-Item -ItemType Directory -Force -Path $dir | Out-Null

Write-Host "=== Бэкап vibe-chat → $dir ==="

# 1. PostgreSQL: логический дамп всей БД vibe
Write-Host "[1/3] PostgreSQL (pg_dump)..."
Invoke-Expression "$Compose exec -T postgres pg_dump -U vibe -d vibe --no-owner --clean --if-exists | gzip > ""$dir/postgres.sql.gz"""
$pgSize = (Get-Item "$dir/postgres.sql.gz").Length
Write-Host ("      OK ({0:N0} байт)" -f $pgSize)

# 2. Silo: выгрузка бакета vibe-files через mc (внутри контейнера Silo уже есть mc)
Write-Host "[2/3] Silo (mc mirror)..."
Invoke-Expression "$Compose exec -T silo mc mirror --overwrite --quiet local/vibe-files /tmp/silo-backup"
Invoke-Expression "$Compose exec -T silo tar -C /tmp -czf - silo-backup > ""$dir/silo.tar.gz"""
Invoke-Expression "$Compose exec -T silo rm -rf /tmp/silo-backup"
$siloSize = (Get-Item "$dir/silo.tar.gz").Length
Write-Host ("      OK ({0:N0} байт)" -f $siloSize)

# 3. Конфигурация (файлы без секретов в git, server.env — локальный секрет)
Write-Host "[3/3] Конфигурация..."
Copy-Item deploy/keycloak/realm-export.json "$dir/realm-export.json" -Force
if (Test-Path deploy/server.env) { Copy-Item deploy/server.env "$dir/server.env" -Force }
Copy-Item deploy/docker-compose.server.yml "$dir/docker-compose.server.yml" -Force
Write-Host "      OK"

Write-Host "=== Готово ==="
Write-Host "Содержимое $dir :"
Get-ChildItem $dir | Format-Table Name, Length -AutoSize
Write-Host ""
Write-Host "Ограничение MVP: Keycloak-учётки (пароли пользователей в его H2) НЕ бэкапятся."
Write-Host "При полной потере стека пользователи восстанавливаются перепривязкой:"
Write-Host "  существующие записи PostgreSQL остаются, но KC-аккаунты нужно пересоздать"
Write-Host "  (сценарий: задеплоить realm, повторно создать пользователей через Admin API)."
Write-Host "Post-MVP: вынести KC на внешний PostgreSQL (db=postgres сервера), тогда в дамп"
Write-Host "добавить схему keycloak — и бэкап станет полным."
