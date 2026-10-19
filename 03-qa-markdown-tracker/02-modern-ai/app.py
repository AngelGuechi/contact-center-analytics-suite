from pathlib import Path
import os
import sys
import tempfile
from datetime import date
import pandas as pd
import streamlit as st

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent))
from qa_shared.core import load_sources,build_report,audit_display,CATALOG,DataError
from qa_shared.paths import source_paths,store_path
from qa_shared.excel_report import write_report
from storage import Store
from ai_service import generate,PRICES

st.set_page_config(page_title='QA workspace',page_icon='📊',layout='wide')
st.markdown('''<style>
.stApp{background:#f6f8fb} h1,h2,h3{color:#182b42}
[data-testid="stMetric"]{background:white;border:1px solid #dce4ef;border-radius:12px;padding:20px}
[data-testid="stSidebar"]{background:#eef2f8}
.stButton>button{border-radius:8px} .block-container{padding-top:2rem}
</style>''',unsafe_allow_html=True)

@st.cache_resource
def database(path):return Store(path)

store=database(str(store_path()))
try:folder,sample=source_paths()
except (DataError,OSError,ValueError) as exc:
    st.error(f'Cannot open the input data: {exc}');st.stop()

def refresh():
    data=load_sources(folder,sample)
    data['sample_path']=str(sample.resolve()) if sample else None
    store.publish(data)
    return data

saved_snapshot = store.snapshot()
if (saved_snapshot is None
    or saved_snapshot.get('source_dir')!=str(folder.resolve())
    or saved_snapshot.get('sample_path')!=(str(sample.resolve()) if sample else None)
    or (saved_snapshot['mode']=='Synthetic demo' and saved_snapshot.get('demo_names_version',0)<1)):
    try:refresh()
    except (DataError,OSError,ValueError) as exc:
        st.error(f'Cannot open the input data: {exc}');st.stop()
data=store.snapshot()
data['coaching']+=store.coaching()
st.title('QA workspace')
st.caption('Scores, existing findings and coaching evidence in one place.')
if data['mode']=='Synthetic demo':
    st.warning('Simulated QA results using names from the source call sample. Scores, teams and coaching are examples; sampled calls still await actual audits.'
               if data.get('demo_names_from_sample') else
               'Synthetic QA demo. Original names in the supplied call sample are retained; its calls still await audit results.')
with st.sidebar:
    st.header('Your report')
    last=max((a['date'] for a in data['audits']),default=(date.today().isoformat()))
    end=st.date_input('Report date',date.fromisoformat(last))
    start=st.date_input('Markdown analysis from',end.replace(day=1))
    filters={}
    for field,label in [('manager','Manager'),('supervisor','Supervisor'),('call_type','Call type'),('markdown','Markdown')]:
        choices=list(CATALOG) if field=='markdown' else sorted({a[field] for a in data['audits']})
        filters[field]=st.selectbox(label,['All',*choices],key='filter_'+field)
    if st.button('Refresh input files',width='stretch'):
        try:
            refresh();st.session_state.pop('ai_draft',None);st.rerun()
        except (DataError,ValueError,OSError) as exc:
            st.error(f'Import stopped: {exc}. The previous data is still displayed.')
    st.caption('Local demo. Shared sign-in and a shared database are a later deployment step.')
try:report=build_report(data,end.isoformat(),filters,start.isoformat())
except (DataError,ValueError) as exc:
    st.error(str(exc));st.stop()
page=st.radio('Page',['Overview','Pivot Tables','Markdowns','Agent & coaching','AI assistant','Settings'],horizontal=True,label_visibility='collapsed')

def fmt(value):return f'{value:.1f}%' if value is not None else 'No data'

def evidence(rows,label='Audit evidence'):
    st.subheader(label)
    if not rows:st.info('No matching audits.');return
    st.dataframe(pd.DataFrame([audit_display(a) for a in rows]),hide_index=True,width='stretch')

def excel_download():
    if st.button('Prepare Excel with PivotTables'):
        with tempfile.TemporaryDirectory() as temp:
            p=write_report(report,Path(temp)/'QA_Review.xlsx')
            st.session_state['excel_export']=(report['snapshot_id'],p.read_bytes())
    export=st.session_state.get('excel_export')
    if export and export[0]==report['snapshot_id']:
        st.download_button('Download Excel report',export[1],'QA_Review.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

if page=='Overview':
    cols=st.columns(4)
    cols[0].metric('QA MTD',fmt(report['qa']))
    cols[1].metric('Audits MTD',report['audit_count'])
    cols[2].metric('Change vs last month',f"{report['change_pp']:+.1f} pp" if report['change_pp'] is not None else 'No data')
    cols[3].metric('QA attention alerts',sum('Needs attention' in a['qa_alert'] for a in report['agents']))
    st.write(report['summary']);st.caption('Calculated summary. All QA scores and statuses come from Python.')
    st.subheader('Your teams')
    st.dataframe(pd.DataFrame([{'Supervisor':r['group'],'QA MTD':fmt(r['qa']),'Audits':r['audits'],'Scored audits':r['scored_audits']} for r in report['rollups']['supervisor']]),hide_index=True,width='stretch')
    st.subheader('QA by audit date')
    history=[a for a in data['audits'] if a['date']<=report['report_date'] and all(a[k]==v for k,v in report['filters'].items() if k!='markdown')]
    if history:
        frame=pd.DataFrame([{'Date':a['date'],'QA':a['score']} for a in history])
        st.line_chart(frame.groupby('Date')['QA'].mean())
    st.caption(f"Last month: {report['previous_start']} to {report['previous_end']}. Missing MTD scores: {report['audit_count']-report['scored_audits']}.")
    excel_download()

elif page=='Pivot Tables':
    st.header('Browse the results')
    st.caption('Choose a view and a group. The evidence appears below. Excel downloads include native PivotTables.')
    view=st.selectbox('Pivot view',['QA by supervisor','QA by agent','Markdowns by call type','Sampled calls by agent'])
    if view.startswith('QA'):
        field='supervisor' if view=='QA by supervisor' else 'agent_id'
        rows=report['pivot_qa']
        if rows:
            frame=pd.DataFrame([{'Group':a['supervisor'] if field=='supervisor' else a['agent']+' ('+a['agent_id']+')','Score':a['score'],'Audit':a['audit_id']} for a in rows])
            pivot=frame.groupby('Group',sort=True).agg(QA_MTD=('Score','mean'),Audits=('Audit','count'),Scored_audits=('Score','count'))
            st.dataframe(pivot,width='stretch',column_config={'QA_MTD':st.column_config.NumberColumn('QA MTD (%)',format='%.1f'),'Scored_audits':'Scored audits'})
            chosen=st.selectbox('Open evidence for',['All',*pivot.index])
            evidence([a for a in rows if chosen=='All' or (a['supervisor'] if field=='supervisor' else a['agent']+' ('+a['agent_id']+')')==chosen])
        else:st.info('No audited results for this scope.')
    elif view=='Markdowns by call type':
        frame=pd.DataFrame([{'Call type':h['call_type'],'Markdown':h['markdown'],'Frequency (%)':h['rate'],'Flags':h['misses'],'Evaluated audits':h['evaluated']} for h in report['heatmap']])
        st.dataframe(frame,hide_index=True,width='stretch')
        ct=st.selectbox('Open call type',['All',*sorted({a['call_type'] for a in report['pivot_markdowns']})])
        md=st.selectbox('Open markdown',list(CATALOG))
        evidence([a for a in report['pivot_markdowns'] if (ct=='All' or a['call_type']==ct) and a['markdowns'].get(md)])
        st.caption('Frequency excludes unknown results. QA MTD includes all scoped audits regardless of markdown selection.')
    else:
        samples=report['sample']
        if samples:
            frame=pd.DataFrame([{'Agent':s['agent']+' ('+s['agent_id']+')','Review status':s['review_status'],'Calls':1} for s in samples])
            st.dataframe(frame.pivot_table(index='Agent',columns='Review status',values='Calls',aggfunc='sum',fill_value=0),width='stretch')
            chosen=st.selectbox('Open sampled agent',['All',*sorted({s['agent']+' ('+s['agent_id']+')' for s in samples})])
            st.dataframe(pd.DataFrame([s for s in samples if chosen=='All' or s['agent']+' ('+s['agent_id']+')'==chosen]),hide_index=True,width='stretch')
        else:st.info('No selected-call file is available.')
        st.caption('This view covers the complete supplied sampling list. Selected calls do not imply completed QA audits.')
    excel_download()

elif page=='Markdowns':
    st.header('The five existing QA findings')
    st.dataframe(pd.DataFrame([{'Markdown':m,'Category':v['category'],'Listed impact (%)':v['impact']} for m,v in CATALOG.items()]),hide_index=True,width='stretch')
    st.dataframe(pd.DataFrame([{k:v for k,v in m.items() if k!='audit_ids'} for m in report['markdowns']]),hide_index=True,width='stretch')
    if report['heatmap']:
        heat=pd.DataFrame(report['heatmap']).pivot(index='call_type',columns='markdown',values='rate')
        st.dataframe(heat.style.background_gradient(cmap='YlOrRd',vmin=0,vmax=100).format('{:.1f}%',na_rep='No data'),width='stretch')
    st.caption('Listed impacts are preserved. Actual points lost come only from exported deductions.')

elif page=='Agent & coaching':
    if st.session_state.pop('coaching_notice',False):st.success('Coaching saved. The comparisons now include it.')
    if not report['agents']:st.info('Import audits and a roster to review agents.');st.stop()
    chosen=st.selectbox('Agent',report['agents'],format_func=lambda a:a['agent']+' ('+a['agent_id']+')')
    st.metric('QA MTD',fmt(chosen['qa']));st.write(chosen['qa_alert'])
    st.dataframe(pd.DataFrame([{'Markdown':s['markdown'],'Status':s['status'],'Change (pp)':s['change_pp'],
                              'Prior audits':s['prior']['evaluated'] if s['prior'] else 0,
                              'Recent audits':s['recent']['evaluated'] if s['recent'] else 0} for s in chosen['statuses']]),hide_index=True,width='stretch')
    st.subheader('Coaching conversation');st.caption('Rule-based GROW guidance. AI drafts are available on the AI assistant page.')
    for label,text in chosen['grow'].items():st.write(f'**{label.title()}:** {text}')
    with st.form('save_coaching'):
        st.subheader('Record agreed coaching')
        coach_day=st.date_input('Coaching date',end)
        md=st.selectbox('Coaching markdown',list(CATALOG))
        owner=st.text_input('Supervisor recording coaching',chosen['supervisor'])
        action=st.text_area('Agreed action')
        follow=st.date_input('Follow-up date',end)
        if st.form_submit_button('Save coaching'):
            try:
                if coach_day>end:raise ValueError('Coaching date must be on or before the report date.')
                store.save_coaching({'agent_id':chosen['agent_id'],'date':coach_day.isoformat(),'markdown':md,'owner':owner,'action':action,'follow_up':follow.isoformat()})
                st.session_state['coaching_notice']=True;st.session_state.pop('ai_draft',None);st.rerun()
            except ValueError as exc:st.error(str(exc))
    evidence([a for a in report['detail'] if a['agent_id']==chosen['agent_id']])

elif page=='AI assistant':
    st.header('Explain the findings')
    st.caption('Original names remain in this dashboard. Only a small masked evidence packet is sent to OpenAI when you press Generate.')
    purpose=st.selectbox('Draft type',['Weekly summary','Agent coaching','Ask QA'])
    agent=None
    if purpose=='Agent coaching':
        if not report['agents']:st.info('No agent audits are available.');st.stop()
        agent=st.selectbox('Agent for AI',report['agents'],format_func=lambda a:a['agent']+' ('+a['agent_id']+')')
    question=st.text_input('Your question',max_chars=500) if purpose=='Ask QA' else ''
    st.write(report['summary'] if agent is None else agent['grow']['reality'])
    if st.button('Generate AI draft'):
        try:
            with st.spinner('Preparing a short evidence-based draft…'):
                draft,refs,label=generate(store,report,st.session_state.get('openai_key') or os.environ.get('OPENAI_API_KEY',''),
                    model=st.session_state.get('model','gpt-5-nano'),agent=agent,question=question,purpose=purpose,budget=st.session_state.get('budget',5.0))
            st.session_state['ai_draft']=(report['snapshot_id'],purpose,agent['agent_id'] if agent else None,question,draft,refs,label)
        except ValueError as exc:st.error(str(exc))
    saved=st.session_state.get('ai_draft')
    if saved and saved[:4]==(report['snapshot_id'],purpose,agent['agent_id'] if agent else None,question):
        _,_,_,_,draft,refs,label=saved
        st.caption(label)
        st.write(draft['summary'])
        for field in ['goal','reality','options','will']:st.write(f'**{field.title()}:** {draft[field]}')
        if draft['themes']:st.write('**Comment themes (limited excerpts):**');st.write(draft['themes'])
        evidence([refs[r] for r in dict.fromkeys(draft['evidence_ids'])],'Audits cited by this draft')
    st.caption('AI text is a draft for review. The tracker preserves evaluator findings and calculated numbers.')

elif page=='Settings':
    st.header('OpenAI and running costs')
    def remember(widget,setting):st.session_state[setting]=st.session_state[widget]
    st.text_input('OpenAI API key',type='password',value=st.session_state.get('openai_key',''),key='_api_widget',
                  on_change=remember,args=('_api_widget','openai_key'),help='Kept in this browser session on the local server; never saved to the database. OPENAI_API_KEY also works.')
    st.selectbox('Model',list(PRICES),index=list(PRICES).index(st.session_state.get('model','gpt-5-nano')),key='_model_widget',on_change=remember,args=('_model_widget','model'))
    st.number_input('Monthly AI budget (USD)',min_value=0.0,max_value=100.0,value=st.session_state.get('budget',5.0),step=1.0,
                   key='_budget_widget',on_change=remember,args=('_budget_widget','budget'))
    st.warning('GPT-5 nano is the lowest-priced option here, but its snapshot is scheduled to retire December 11, 2026. GPT-6 Luna is available as an explicit alternative.')
    agents=st.number_input('Agents for expected cost',min_value=1,max_value=5000,value=42)
    input_tokens=st.number_input('Expected input tokens per request',min_value=100,value=2000,step=100)
    output_tokens=st.number_input('Expected billable output tokens per request',min_value=100,max_value=2000,value=800,step=100)
    p=PRICES[st.session_state.get('model','gpt-5-nano')]
    requests_count=agents*4+4+100
    estimated=requests_count*(input_tokens*p[0]+output_tokens*p[2])/1_000_000
    st.metric('Expected monthly API cost',f'${estimated:.2f}')
    st.caption(f'{requests_count:,} requests: four coaching drafts per agent, four summaries, and one hundred questions. Output includes reasoning tokens. Hosting, licenses, labor, taxes and cache-write surcharges are excluded.')
    st.metric('Tracked usage and pending reservations',f'${store.spend():.4f}')
    st.caption('Tracked cost is an estimate from token usage. Unknown charges keep a conservative reservation. Check the OpenAI billing page for the invoice.')
    st.dataframe(pd.DataFrame(store.ledger()),hide_index=True,width='stretch')
    st.subheader('Input files')
    st.write(str(folder));st.write(data['input_files'])
    st.dataframe(pd.DataFrame(data['issues']),hide_index=True,width='stretch')
    st.markdown('[GPT-5 nano pricing](https://developers.openai.com/api/docs/models/gpt-5-nano) · [GPT-6 Luna pricing](https://developers.openai.com/api/docs/models/gpt-6-luna)')
