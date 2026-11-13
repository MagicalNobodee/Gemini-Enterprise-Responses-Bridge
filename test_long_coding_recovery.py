"""Regression of the 2026-11-13 large write / duplicate check / poisoned history failure."""
import json
import pytest
from tool_calling import BrowserTaskFailure, ToolProtocolError, ToolStreamProcessor, parse_assistant_output
from test_responses import browser, packets

TOOLS = [{'type':'function','name':'functions.exec_command','parameters':{'type':'object'}}]
PARSE_TOOLS = [{'type':'function','function':{'name':'functions.exec_command','parameters':{'type':'object'}}}]
FALLBACK = "I couldn't complete this request. If it needs a file, please attach it in the chat."


def call(cmd):
    return '```codex_tool_call\n' + json.dumps({'name':'functions.exec_command','arguments':{'cmd':cmd}}) + '\n```\n'


@pytest.mark.parametrize('stream', [False, True])
def test_long_write_is_never_dispatched_in_parallel_or_replayed_after_result(stream):
    cmd = "cat <<'EOF' > main.js\n" + ('// fixture data\n' * 1800) + 'EOF'
    bad = call(cmd) + call('ls -la main.js') + call('ls -la main.js')
    with browser([bad]) as (client,commands):
        result=client.post('/v1/responses',json={'model':'gemini-4-carbon','tools':TOOLS,'stream':stream,'input':'Write main.js then inspect its size.'})
        if stream:
            assert packets(result.text)[-1]['type']=='response.failed'
        else:
            assert result.status_code==502
        assert len(commands)==1
    with browser([call(cmd),call('ls -la main.js'),'verified']) as (client,commands):
        payload={'model':'gemini-4-carbon','tools':TOOLS,'stream':stream,'input':'Write main.js then inspect its size.'}
        def send(p):
            result=client.post('/v1/responses',json=p)
            return packets(result.text)[-1]['response'] if stream else result.json()
        first=send(payload)
        action=next(o for o in first['output'] if o['type']=='function_call')
        assert json.loads(action['arguments'])=={'cmd':cmd}
        result=send({**payload,'previous_response_id':first['id'],'input':[{'type':'function_call_output','call_id':action['call_id'],'output':'write successful; file size=27000'}]})
        check=next(o for o in result['output'] if o['type']=='function_call')
        assert json.loads(check['arguments'])=={'cmd':'ls -la main.js'}
        assert len(commands)==2 and not commands[-1]['reset_chat']
        assert cmd not in commands[-1]['prompt']
        end=send({**payload,'previous_response_id':result['id'],'input':[{'type':'function_call_output','call_id':check['call_id'],'output':'main.js 27000 bytes'}]})
        assert end['status']=='completed' and len(commands)==3


@pytest.mark.parametrize('stream', [False, True])
def test_cloud_fallback_fails_once_and_forces_clean_next_turn(stream):
    with browser([call('cat main.js'), FALLBACK, 'recovered']) as (client, commands):
        payload={'model':'gemini-4-carbon','tools':TOOLS,'stream':stream,'prompt_cache_key':'fallback-regression','input':'Read main.js'}
        result=client.post('/v1/responses',json=payload)
        first=packets(result.text)[-1]['response'] if stream else result.json()
        call_id=first['output'][0]['call_id']
        result=client.post('/v1/responses',json={**payload,'previous_response_id':first['id'],
            'input':[{'type':'function_call_output','call_id':call_id,'output':'// existing content'}]})
        if stream:
            events=packets(result.text)
            assert events[-1]['type']=='response.failed'
            assert not any(e['type']=='response.completed' for e in events)
            assert FALLBACK not in ''.join(e.get('delta','') for e in events)
        else:
            assert result.status_code==502
        assert len(commands)==2  # no blind retry of an upstream failure
        assert client.get('/api/status').json()['hub']['total_errors']==1
        client.post('/v1/responses',json={**payload,'previous_response_id':first['id'],
            'input':[{'type':'function_call_output','call_id':call_id,'output':'// existing content'},{'role':'user','content':'Continue from actual results'}]})
        assert commands[-1]['reset_chat'] is True
        assert '// existing content' in commands[-1]['prompt']


def test_fallback_is_buffered_but_quoted_explanations_are_preserved():
    for width in [1, 13, 1000]:
        processor=ToolStreamProcessor(PARSE_TOOLS)
        for i in range(0,len(FALLBACK),width):
            assert processor.feed(FALLBACK[i:i+width])==[]
        with pytest.raises(BrowserTaskFailure): processor.finalize()
    text='The webpage reported: "'+FALLBACK+'" Please inspect the gateway.'
    processor=ToolStreamProcessor(PARSE_TOOLS)
    out=[]
    for c in text: out.extend(processor.feed(c))
    tail,_=processor.finalize()
    assert ''.join(out+tail)==text


def test_parallel_independent_reads_work_but_patches_and_checks_do_not_race():
    reads = call('ls -la main.js') + call('ls -la main.js') + call('cat other.js')
    parsed=parse_assistant_output(reads,PARSE_TOOLS)
    assert len(parsed.tool_calls)==2
    with pytest.raises(ToolProtocolError):
        parse_assistant_output(call('printf new > main.js')+call('cat main.js'),PARSE_TOOLS)
