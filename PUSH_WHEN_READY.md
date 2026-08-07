# Пуш в GitHub, когда будет URL

Репозиторий уже инициализирован локально, remote ещё не добавлен.  
Подставьте свой URL вместо `YOUR_REPO_URL` и выполните шаги ниже (или вставьте промпт агенту).

## Быстрые шаги (вручную)

```bash
cd /Users/timofejmarusko/Documents/VisualStudioCodeRepos/AutoApply

# Проверка: .env НЕ должен попасть в индекс
git status
git check-ignore -v .env

git remote add origin YOUR_REPO_URL
# если origin уже есть:
# git remote set-url origin YOUR_REPO_URL

git branch -M main
git push -u origin main
git remote -v
git status
```

Не используйте `git push --force` без явной необходимости.

## Промпт для Cursor (скопировать целиком)

```
В каталоге /Users/timofejmarusko/Documents/VisualStudioCodeRepos/AutoApply уже есть локальный git-репозиторий с коммитами (auto-apply-app в корне). Нужно только опубликовать.

URL репозитория: YOUR_REPO_URL

Сделай:
1. Проверь git status / remote — не коммить .env и секреты.
2. Добавь remote origin на указанный URL (или set-url, если origin уже есть).
3. Переименуй ветку в main при необходимости: git branch -M main
4. Запушь: git push -u origin main
5. НЕ делай force push.
6. В конце покажи: git remote -v, git status, и подтверждение успешного push.

Ответь по-русски кратко.
```
