"""真实存储与编排测试；仅替换外部网页/模型边界，不污染开发库。"""
import asyncio
import json
import pytest
from app import market_intake as intake, market_research as research

TOPIC = 'embodied-intelligence'
CATEGORY = 'robot-learning-data'
URL = 'https://example.com/research'
QUOTE = 'The robot completes the defined task in a controlled laboratory.'

@pytest.fixture(autouse=True)
def jobs(monkeypatch):
    intake.init_tables()
    monkeypatch.setattr(intake, '_locks', {})
    monkeypatch.setattr(intake, '_capacity', asyncio.Semaphore(2))


def new_job(**kwargs):
    return intake.create_job(tenant_id=kwargs.get('tenant_id', 't1'), user_id='u1', topic_id=TOPIC, url=kwargs.get('url', URL))


def fake_document(url):
    return {'url': url, 'title': 'Research', 'text': QUOTE * 4, 'fetched_at': research._now()}


async def fake_generate(schema, instructions, material):
    if schema is intake.Extracted:
        return intake.Extracted(relevant=True, category_id=CATEGORY, title='限定任务实验', summary='发布方报告实验进展',
            facts=[{'text': '在受控实验中完成限定任务', 'quote': QUOTE}], analysis='不能外推真实场景', uncertainty='缺少外部复现',
            signals='跟踪真实部署', stage='厂商自报实验', tier='高', priority='A')
    if 'observations' in material:
        ids = [i['id'] for i in material['observations']]
    else:
        ids = list({eid for c in material['categories'] for eid in c['report']['evidence_ids']})
    return intake.Report(title='有边界的趋势判断', conclusion='仍需客户侧验证',
        content_markdown='\n\n'.join('## ' + h + '\n实验进展仍需外部验证，不能据此判断商业化成熟。' * 2 for h in ['技术进展','市场与应用','产业发展','机会与行动','未来跟踪','风险与边界']),
        confidence='low', evidence_ids=ids)


def test_link_to_observation_to_category_to_topic_and_repeat_is_idempotent(monkeypatch):
    monkeypatch.setattr(intake, 'fetch_document', fake_document)
    calls = []
    async def generate(*args):
        calls.append(args[0]); return await fake_generate(*args)
    monkeypatch.setattr(intake, 'generate', generate)
    job = new_job()
    asyncio.run(intake.process(job))
    done = intake.get_job('t1', job['id'])
    assert done['status'] == done['stage'] == 'done'
    assert done['observation_id'] and done['category_report_id'] and done['topic_report_id']
    item = research.get_observation(tenant_id='t1', observation_id=done['observation_id'])
    assert item['research_metadata']['stage'] == '厂商自报实验'
    assert item['sources'][0]['url'] == URL
    overview = research.get_topic_judgement_overview(tenant_id='t1', topic_id=TOPIC)
    assert overview['topic_report']['report']['evidence_ids'] == [item['id']]
    assert overview['topic_report']['freshness'] == 'current'
    repeated = new_job(url=URL + '?utm_source=test')
    asyncio.run(intake.process(repeated))
    assert len(calls) == 3  # 重复链接不再调用模型，不新增研判版本
    assert len(research.list_workbench(tenant_id='t1', topic_id=TOPIC)['items']) == 1
    assert len(research.list_judgement_history(tenant_id='t1', topic_id=TOPIC)) == 1


def test_failed_topic_generation_resumes_without_fetch_extract_or_duplicate_reports(monkeypatch):
    monkeypatch.setattr(intake, 'fetch_document', fake_document)
    failed = False
    async def generate(schema, prompt, material):
        nonlocal failed
        if 'categories' in material and not failed:
            failed = True
            raise ValueError('暂时无法生成主题研判')
        return await fake_generate(schema, prompt, material)
    monkeypatch.setattr(intake, 'generate', generate)
    job = new_job()
    asyncio.run(intake.process(job))
    partial = intake.get_job('t1', job['id'])
    assert partial['status'] == 'failed' and partial['stage'] == 'topic'
    assert partial['observation_id'] and partial['category_report_id']
    monkeypatch.setattr(intake, 'fetch_document', lambda _: pytest.fail('不应重新抓取'))
    asyncio.run(intake.process(partial))
    done = intake.get_job('t1', job['id'])
    assert done['status'] == 'done'
    assert done['observation_id'] == partial['observation_id']
    assert len(research.list_judgement_history(tenant_id='t1', topic_id=TOPIC, category_id=CATEGORY)) == 1


def test_untraceable_fact_is_not_saved(monkeypatch):
    monkeypatch.setattr(intake, 'fetch_document', fake_document)
    async def bad(schema, prompt, material):
        out = await fake_generate(schema, prompt, material)
        out.facts[0].quote = 'This quote never appeared in the actual document.'
        return out
    monkeypatch.setattr(intake, 'generate', bad)
    job = new_job()
    asyncio.run(intake.process(job))
    assert intake.get_job('t1', job['id'])['status'] == 'failed'
    assert not research.list_workbench(tenant_id='t1', topic_id=TOPIC)['items']


@pytest.mark.parametrize('url', ['http://127.0.0.1/a', 'http://localhost/a', 'http://169.254.169.254/latest', 'http://10.0.0.1/a', 'file:///etc/passwd', 'https://user:secret@example.com/a'])
def test_private_or_credential_links_rejected(url):
    with pytest.raises(ValueError): intake.public_url(url)


def test_redirect_dns_and_payload_limits_are_checked(monkeypatch):
    monkeypatch.setattr(intake.socket, 'getaddrinfo', lambda *a, **kw: [(2, 1, 6, '', ('127.0.0.1', 80))])
    with pytest.raises(ValueError, match='内网'): intake.fetch_document(URL)


def test_queued_submission_deduplicates_tracking_query_and_recovery_keeps_tenant_scope():
    first = new_job()
    assert new_job(url=URL + '?utm_source=again')['id'] == first['id']
    other = new_job(tenant_id='t2')
    assert other['id'] != first['id']
    intake.recover()
    assert intake.get_job('t1', first['id'])['status'] == 'interrupted'
    assert intake.get_job('t2', first['id']) is None
    public = intake.list_jobs('t1', 'u1')
    assert len(public) == 1
    assert 'document_json' not in public[0] and 'tenant_id' not in public[0]


def test_failed_process_does_not_restore_deleted_observation(monkeypatch):
    saved = research.save_source_observation(tenant_id='t1', topic_id=TOPIC, category_id=CATEGORY, title='已删除', sources=[{'url':URL}])['item']
    research.soft_delete_observation(tenant_id='t1', observation_id=saved['id'])
    job = new_job()
    asyncio.run(intake.process(job))
    assert '回收站' in intake.get_job('t1', job['id'])['error']
    assert research.get_observation(tenant_id='t1', observation_id=saved['id']) is None


def test_public_redirect_to_private_host_is_rejected(monkeypatch):
    monkeypatch.setattr(intake.socket, 'getaddrinfo', lambda *a, **k: [(2,1,6,'',('93.184.216.34',443))])
    class Response:
        status=302
        def getheader(self,name): return 'http://127.0.0.1/private'
    class Connection:
        def __init__(self,*a,**k): pass
        def request(self,*a,**k): pass
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(intake.http.client,'HTTPSConnection',Connection)
    with pytest.raises(ValueError, match='内网'): intake.fetch_document(URL)


def test_new_data_during_generation_requires_retry_instead_of_saving_stale_judgement(monkeypatch):
    monkeypatch.setattr(intake,'fetch_document',fake_document)
    changed=False
    async def generate(schema,prompt,material):
        nonlocal changed
        output=await fake_generate(schema,prompt,material)
        if schema is intake.Report and 'observations' in material and not changed:
            changed=True
            research.create_observation(tenant_id='t1',topic_id=TOPIC,category_id=CATEGORY,title='生成期间的新记录',sources=[{'url':'https://example.com/new'}])
        return output
    monkeypatch.setattr(intake,'generate',generate)
    job=new_job()
    asyncio.run(intake.process(job))
    failed=intake.get_job('t1',job['id'])
    assert failed['status']=='failed' and '资料发生变化' in failed['error']
    assert not research.get_judgement(tenant_id='t1',topic_id=TOPIC,category_id=CATEGORY)['report']
    asyncio.run(intake.process(failed))
    assert intake.get_job('t1',job['id'])['status']=='done'


def test_source_tools_enqueue_same_followup_and_unclassified_record_is_classified(monkeypatch):
    async def generate(schema,prompt,material):
        if schema is intake.Classification:
            return intake.Classification(relevant=True,category_id=CATEGORY)
        return await fake_generate(schema,prompt,material)
    monkeypatch.setattr(intake,'generate',generate)
    saved=research.save_source_observation(tenant_id='t1',topic_id=TOPIC,title='待分类的来源',summary='机器人数据集',sources=[{'url':URL}],created_by='u1')['item']
    jobs=intake.list_jobs('t1','u1')
    assert len(jobs)==1 and jobs[0]['observation_id']==saved['id']
    monkeypatch.setattr(intake,'fetch_document',lambda _:pytest.fail('已有原文不再抓取'))
    asyncio.run(intake.process(intake.get_job('t1',jobs[0]['id'])))
    assert intake.get_job('t1',jobs[0]['id'])['status']=='done'
    assert research.get_observation(tenant_id='t1',observation_id=saved['id'])['category_id']==CATEGORY


def test_deleted_last_evidence_in_one_category_does_not_block_remaining_topic(monkeypatch):
    monkeypatch.setattr(intake,'fetch_document',fake_document)
    monkeypatch.setattr(intake,'generate',fake_generate)
    first=new_job()
    asyncio.run(intake.process(first))
    original=intake.get_job('t1',first['id'])
    second=research.create_observation(tenant_id='t1',topic_id=TOPIC,category_id='vla-embodied-reasoning',title='另一个领域的证据',sources=[{'url':'https://example.com/second'}],created_by='u1')
    research.soft_delete_observation(tenant_id='t1',observation_id=original['observation_id'])
    intake.enqueue_topic('t1',TOPIC,'u1')
    jobs=intake.list_jobs('t1','u1')
    followup=next(j for j in jobs if j['observation_id']==second['id'])
    asyncio.run(intake.process(intake.get_job('t1',followup['id'])))
    assert intake.get_job('t1',followup['id'])['status']=='done'
    overview=research.get_topic_judgement_overview(tenant_id='t1',topic_id=TOPIC)
    assert overview['topic_report']['freshness']=='current'
    assert overview['topic_report']['report']['evidence_ids']==[second['id']]
    old=next(c for c in overview['categories'] if c['id']==CATEGORY)
    assert old['evidence_count']==0 and old['freshness']=='stale'


def test_configured_thinking_model_can_use_plain_json_without_forced_tools(monkeypatch):
    from app import catalog, compiler
    from types import SimpleNamespace
    calls=[]
    class Model:
        async def ainvoke(self,messages):
            calls.append(messages)
            return SimpleNamespace(content='```json\n'+json.dumps({'relevant':True,'category_id':CATEGORY})+'\n```')
    monkeypatch.setattr(catalog,'get_employee_config',lambda _: {'model':'test-model'})
    monkeypatch.setattr(compiler,'_init_model',lambda _:Model())
    result=asyncio.run(intake.generate(intake.Classification,'分类',{'text':'机器人训练数据'}))
    assert result.category_id==CATEGORY and len(calls)==1
    assert 'JSON Schema' in calls[0][0]['content']
