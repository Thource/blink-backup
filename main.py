import logging
import os
import string
import time
from shutil import copyfileobj
from dotenv import load_dotenv
from slugify import slugify
import dateutil.parser

from blinkpy import api
from blinkpy.helpers.util import json_load, local_storage_clip_url_template
from blinkpy.blinkpy import Blink
from blinkpy.auth import Auth
from blinkpy.sync_module import BlinkSyncModule, _LOGGER

load_dotenv()

_LOGGER.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)

# add ch to logger
_LOGGER.addHandler(ch)

blink = Blink()
saved_auth = json_load('.blink-auth')
if saved_auth is not None:
    print('Authed from file')
    auth = Auth(saved_auth)
else:
    print('Authed from .env')
    auth = Auth({"username": os.getenv('BLINK_USERNAME'), "password": os.getenv('BLINK_PASSWORD')})
blink.auth = auth
blink.start()

blink.save('.blink-auth')


def fetch_manifest(sync_id, network_id):
    print('Fetching manifest... ', end='')
    manifest_request = api.request_local_storage_manifest(blink, network_id, sync_id)
    manifest_request_id = manifest_request.get('id')
    if manifest_request_id is None:
        print(f'Error requesting manifest: {manifest_request}')
        return None

    while not api.request_command_status(blink, network_id, manifest_request_id).get('complete'):
        time.sleep(2)

    print('DONE')
    return api.get_local_storage_manifest(blink, network_id, sync_id, manifest_request_id)


sync_module: BlinkSyncModule
for sync_module in blink.sync.values():
    sync_id = sync_module.sync_id
    network_id = sync_module.network_id
    vids_dir = f'vids/{sync_id}'
    os.makedirs(vids_dir, exist_ok=True)

    manifest = fetch_manifest(sync_id, network_id)
    if manifest is None:
        continue

    print('Fetching clips... ', end='')
    manifest_id = manifest.get('manifest_id')
    clips = manifest.get('clips')
    if clips is None:
        print(f'Error fetching clips: {manifest}')
        continue

    clips.reverse()
    print('DONE')

    last_timestamp = 0
    try:
        with open(f'{vids_dir}/last-timestamp') as f:
            last_timestamp = int(f.read())
    except OSError:
        pass

    for clip in clips:
        created_at = dateutil.parser.parse(clip.get('created_at'))
        if int(created_at.timestamp()) <= last_timestamp:
            continue

        last_timestamp = int(created_at.timestamp())
        clip_id = clip.get('id')
        clip_request = api.request_local_storage_clip(blink, network_id, sync_id, manifest_id, clip_id)
        clip_request_id = clip_request.get('id')

        print(f'Downloading video from {clip.get("created_at")}...', end='')
        while True:
            command_status = api.request_command_status(blink, network_id, clip_request_id)
            if command_status.get('complete'):
                break

            print('.', end='')
            time.sleep(2)

        clip_res = api.http_get(blink,
                                blink.urls.base_url + string.Template(local_storage_clip_url_template()).substitute(
                                    account_id=blink.account_id, network_id=network_id, sync_id=sync_id,
                                    manifest_id=manifest_id, clip_id=clip_id), stream=True, json=False)
        filename = slugify(f'{clip.get("created_at")}-{clip.get("camera_name")}')
        with open(f'{vids_dir}/{filename}.mp4', "wb") as video_file:
            copyfileobj(clip_res.raw, video_file)
        with open(f'{vids_dir}/last-timestamp', 'w') as f:
            f.write(str(last_timestamp))
        print(' DONE')
