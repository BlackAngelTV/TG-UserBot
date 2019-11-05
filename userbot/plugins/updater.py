# TG-UserBot - A modular Telegram UserBot script for Python.
# Copyright (C) 2019  Kandarp <https://github.com/kandnub>
#
# TG-UserBot is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# TG-UserBot is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with TG-UserBot.  If not, see <https://www.gnu.org/licenses/>.


import asyncio
import datetime
import os.path
import sys

import git
import heroku3

from userbot import client, LOGGER
from userbot.utils.helpers import restart, _humanfriendly_seconds
from userbot.utils.events import NewMessage


basedir = os.path.abspath(os.path.curdir)
author_link = "[{author}]({url}commits?author={author})"
summary = "\n[{rev}]({url}commit/{sha}) `{summary}`\n"
commited = "{committer}` committed {elapsed} ago`\n"
authored = "{author}` authored and `{committer}` committed {elapsed} ago`\n"


@client.onMessage(
    command="update",
    outgoing=True, regex="update(?: |$)(reset|add)?$", builtin=True
)
async def updater(event: NewMessage.Event) -> None:
    """Pull newest changes from the official repo and update the script/app."""
    arg = event.matches[0].group(1)
    main_repo = "https://github.com/kandnub/TG-UserBot.git"
    try:
        repo = git.Repo(basedir)
        fetched_itmes = repo.remotes.origin.fetch()
    except git.exc.NoSuchPathError as path:
        await event.answer(f"`Couldn't find {path}!`")
        return
    except git.exc.GitCommandError as command:
        await event.answer(
            f"`An error occured trying to get the Git Repo.`\n`{command}`"
        )
        return
    except git.exc.InvalidGitRepositoryError:
        repo = git.Repo.init(basedir)
        origin = repo.create_remote('origin', main_repo)
        if not origin.exists():
            await event.answer(
                "`The main repository does not exist. Remote is invalid!`"
            )
            return
        fetched_itmes = origin.fetch()
        repo.create_head('master', origin.refs.master).set_tracking_branch(
            origin.refs.master
        ).checkout()
    fetched_commits = repo.iter_commits(f"HEAD..{fetched_itmes[0].ref.name}")

    await event.answer("`Checking for updates!`")
    untracked_files = repo.untracked_files
    old_commit = repo.head.commit
    if arg == "add":
        repo.index.add(untracked_files, force=True)
        repo.index.commit("[TG-UserBot] Updater: Untracked files")
    elif arg == "reset":
        repo.head.reset('--hard')

    try:
        pull = repo.remotes.origin.pull()
    except git.exc.GitCommandError as command:
        text = (
            "`An error occured trying to Git pull:`\n`{0}`\n\n"
            "`You may use` **{1}update reset** `or` **{1}update add** "
            "`to reset your repo or add and commit your changes as well.`"
        )
        prefix = client.prefix if client.prefix is not None else '.'
        await event.answer(text.format(command, prefix))
        return

    new_commit = repo.head.commit
    if old_commit == new_commit:
        await event.answer("`Already up-to-date!`")
        return

    remote_url = repo.remote().url.replace(".git", '/')
    if remote_url[-1] != '/':
        remote_url = remote_url + '/'

    now = datetime.datetime.now(datetime.timezone.utc)
    def_changelog = changelog = "**TG-UserBot changelog:**"
    for commit in fetched_commits:
        changelog += summary.format(
            rev=repo.git.rev_parse(commit.hexsha, short=7),
            summary=commit.summary, url=remote_url, sha=commit.hexsha
        )
        ago = (now - commit.committed_datetime).total_seconds()
        elspased = (await _humanfriendly_seconds(ago)).split(',')[0]
        committers_link = author_link.format(
            author=commit.committer, url=remote_url
        )
        authors_link = author_link.format(
            author=commit.author, url=remote_url
        )
        if commit.author == commit.committer:
            committed = commited.format(
                committer=committers_link,
                elapsed=elspased
            )
        else:
            committed = authored.format(
                author=authors_link,
                committer=committers_link,
                elapsed=elspased
            )
        changelog += f"{committed:>{len(committed) + 8}}"
    if changelog == def_changelog:
        changelog = "`No changelog for you! IDK what happened.`"

    toast = await event.answer(
        "`Successfully pulled the new commits. Updating the bot!`",
        log=("update", changelog.strip())
    )
    if not client.logger:
        await event.answer(
            changelog.strip(),
            reply_to=toast.id,
            link_preview=False
        )

    os.environ['userbot_update'] = "True"
    heroku_api_key = client.config['api_keys'].get('api_key_heroku', False)
    if os.getenv("DYNO", False) and heroku_api_key:
        heroku_conn = heroku3.from_key(heroku_api_key)
        heroku_app = None
        for app in heroku_conn.apps():
            if app.name == os.getenv('HEROKU_APP_NAME', ''):
                heroku_app = app
                break
        if heroku_app is None:
            await event.answer(
                "`You seem to be running on Heroku "
                "with an invalid environment. Couldn't update the app.`\n"
                "`The changes will be reverted upon dyno restart.`"
            )
            await asyncio.sleep(2)
            await updated_pip_modules(event, pull, repo, new_commit)
            await restart(event)
        else:
            # Don't update the telethon environment varaibles
            userbot_config = client.config['userbot']
            app.config().update(dict(userbot_config))
            app.config().update({
                'userbot_restarted': f"{event.chat_id}/{event.message.id}",
                'userbot_update': "True"
            })
            if event.client.disabled_commands:
                disabled_list = ", ".join(client.disabled_commands.keys())
                app.config().update(
                    {'userbot_disabled_commands': disabled_list}
                )

            url = f"https://api:{heroku_api_key}@git.heroku.com/{app.name}.git"
            if "heroku" in repo.remotes:
                repo.remotes['heroku'].set_url(url)
            else:
                repo.create_remote('heroku', url)
            if repo.untracked_files:
                repo.index.add(untracked_files, force=True)
                repo.index.commit("[TG-UserBot] Updater: Untracked files")
            app.enable_feature('runtime-dyno-metadata')
            await event.answer(
                "`Pushing all the changes to Heroku. Might take a while.`"
            )
            remote = repo.remotes['heroku']
            try:
                remote.push(
                    refspec=f'{repo.active_branch.name}:master',
                    force=True
                )
                await event.answer("`There was nothing to push to Heroku?`")
            except git.exc.GitCommandError as command:
                await event.answer(
                    "`An error occured trying to pull and push to Heorku`"
                    f"\n`{command}`"
                )
                LOGGER.exception(command)
    else:
        await updated_pip_modules(event, pull, repo, new_commit)
        await restart(event)


async def updated_pip_modules(event, pull, repo, new_commit):
    pulled = getattr(pull, repo.active_branch.name, False)
    if pulled and pulled.old_commit:
        for f in new_commit.diff(pulled.old_commit):
            if f.b_path == "requirements.txt":
                await event.answer("`Updating the pip requirements!`")
                await update_requirements()


async def update_requirements():
    reqs = os.path.join(basedir, "requirements.txt")
    try:
        await asyncio.create_subprocess_shell(
            ' '.join(sys.executable, "-m", "pip", "install", "-r", str(reqs))
        ).communicate()
    except Exception as e:
        LOGGER.exception(e)
