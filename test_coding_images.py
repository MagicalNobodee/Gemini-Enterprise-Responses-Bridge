"""Coding histories retain image references without uploading old screenshots again."""
import base64
import json
from pathlib import Path

import pytest

from extension_exporter import render_spark_icon_png
from test_responses import browser, packets

TOOLS = [{'type': 'function', 'name': 'exec_command', 'parameters': {'type': 'object'}}]
CALL = '```codex_tool_call\n' + json.dumps({'name': 'exec_command', 'arguments': {'cmd': 'ls /local/project'}}) + '\n```\n'


def image(size=16):
    return {'type': 'input_image', 'image_url': 'data:image/png;base64,' + base64.b64encode(render_spark_icon_png(size)).decode()}


def history():
    return [
        {'role': 'user', 'content': [{'type': 'input_text', 'text': 'Inspect the local project screenshots.'}] + [image(16+i) for i in range(8)]},
        {'role': 'assistant', 'content': 'The eight scenes have been inspected.'},
        {'role': 'user', 'content': 'Continue editing /local/project.'},
    ]


@pytest.mark.parametrize('stream', [False, True])
def test_repacked_coding_history_does_not_upload_eight_old_screenshots(stream):
    with browser([CALL], auto_reset_new_chat=True) as (client, commands):
        result = client.post('/v1/responses', json={'input': history(), 'tools': TOOLS, 'stream': stream})
        response = packets(result.text)[-1]['response'] if stream else result.json()
        assert response['status'] == 'completed'
        assert response['output'][0]['type'] == 'function_call'
        assert not commands[0].get('attachments')
        assert '[Image attachment ' not in commands[0]['prompt']
        assert commands[0]['prompt'].count('[Historical image reference ') == 8
        assert 'not attached' in commands[0]['prompt']
        assert 'eight scenes have been inspected' in commands[0]['prompt']
        assert '/local/project' in commands[0]['prompt']


@pytest.mark.parametrize('stream', [False, True])
def test_new_image_tool_result_uploads_once_and_preserves_incremental_history(stream):
    with browser([CALL, CALL, 'verified'], auto_reset_new_chat=True) as (client, commands):
        first = client.post('/v1/responses', json={'input': history(), 'tools': TOOLS}).json()
        call1 = first['output'][0]
        second = client.post('/v1/responses', json={
            'previous_response_id': first['id'], 'tools': TOOLS,
            'input': [{'type': 'function_call_output', 'call_id': call1['call_id'], 'output': [
                {'type': 'input_text', 'text': 'New screenshot from the local image viewer.'}, image(48)]}],
        }).json()
        assert len(commands[1]['attachments']) == 1
        assert not commands[1]['reset_chat']
        call2 = second['output'][0]
        third = client.post('/v1/responses', json={
            'previous_response_id': second['id'], 'tools': TOOLS, 'stream': stream,
            'input': [{'type': 'function_call_output', 'call_id': call2['call_id'], 'output': 'local check passed'}],
        })
        response = packets(third.text)[-1]['response'] if stream else third.json()
        assert response['status'] == 'completed'
        assert not commands[2].get('attachments')
        assert not commands[2]['reset_chat']
        assert 'local check passed' in commands[2]['prompt']
        assert 'eight scenes have been inspected' not in commands[2]['prompt']
        assert 'host-native' in commands[2]['prompt']
        assert 'client computer' in commands[2]['prompt']


def test_explicitly_supplied_old_image_is_uploaded_again():
    messages = history()
    messages[-1]['content'] = [{'type': 'input_text', 'text': 'Inspect this image again.'}, image()]
    with browser(['reinspected']) as (client, commands):
        assert client.post('/v1/responses', json={'input': messages, 'tools': TOOLS}).status_code == 200
        assert len(commands[0]['attachments']) == 1
        assert commands[0]['prompt'].count('[Historical image reference ') == 7


def test_normal_multimodal_chat_keeps_history_images():
    with browser(['compared']) as (client, commands):
        assert client.post('/v1/responses', json={'input': history()}).status_code == 200
        assert len(commands[0]['attachments']) == 8


def test_chat_completions_uses_the_same_image_policy():
    messages = history()
    messages[0]['content'] = [dict(p, type='image_url', image_url={'url': p['image_url']}) if p['type']=='input_image' else p for p in messages[0]['content']]
    with browser(['continued']) as (client, commands):
        result = client.post('/v1/chat/completions', json={'messages': messages, 'tools': [
            {'type': 'function', 'function': TOOLS[0]}]})
        assert result.status_code == 200
        assert not commands[0].get('attachments')
        assert commands[0]['prompt'].count('[Historical image reference ') == 8


def test_eight_fresh_images_are_still_uploaded_and_invalid_fresh_images_fail():
    first_user = history()[0]
    with browser(['inspected']) as (client, commands):
        response = client.post('/v1/responses', json={'input': [first_user], 'tools': TOOLS})
        assert response.status_code == 200
        assert len(commands[0]['attachments']) == 8
        assert '[Historical image reference ' not in commands[0]['prompt']
    with browser([]) as (client, commands):
        response = client.post('/v1/responses', json={'input': [{'role': 'user', 'content': [
            {'type': 'input_image', 'image_url': 'data:image/png;base64,bm90LWFuLWltYWdl'}]}], 'tools': TOOLS})
        assert response.status_code == 400
        assert not commands


def test_missing_historical_image_file_does_not_block_local_code_work():
    messages = history()
    messages[0]['content'] = [{'type': 'input_image', 'file_id': 'file_' + 'a'*32}]
    with browser(['continued']) as (client, commands):
        response = client.post('/v1/responses', json={'input': messages, 'tools': TOOLS})
        assert response.status_code == 200
        assert not commands[0].get('attachments')
        assert 'not attached' in commands[0]['prompt']


def test_cached_large_image_keeps_its_original_identity():
    from media_inputs import FileStore, compact_messages_for_store, extract_part_marker
    from schemas import ChatMessage
    import tempfile
    # The extra data is a valid PNG ancillary payload; the cache threshold is 128 KiB.
    raw = render_spark_icon_png(16) + b'padding' * 20000
    part = {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(raw).decode()}}
    original = extract_part_marker(part)
    with tempfile.TemporaryDirectory() as directory:
        compacted = compact_messages_for_store([{'role': 'user', 'content': [part]}], FileStore(Path(directory)))
        cached = compacted[0]['content'][0]
        assert cached['image_url']['url'].startswith('file_')
        assert extract_part_marker(cached) == original
        assert ChatMessage(**compacted[0]).text_content() == original


def test_new_copy_of_cached_image_does_not_require_old_cache_file():
    from media_inputs import extract_part_marker
    part = image()
    marker = extract_part_marker(part)
    # Test the shared collector directly: public Responses normalization deliberately
    # omits internal cache metadata; ResponseStore reconstructs it as ChatMessage.
    from media_inputs import collect_attachments
    from schemas import ChatMessage
    stored = [ChatMessage(role='user', content=[{'type': 'image_url', 'image_url': {'url': 'file_'+'a'*32}, '_bridge_image_marker': marker}]),
              ChatMessage(role='assistant', content='inspected'), ChatMessage(role='user', content=[part])]
    attachments = collect_attachments(stored, pending_images_only=True)
    assert len(attachments) == 1 and attachments[0]['data_url'] == part['image_url']
