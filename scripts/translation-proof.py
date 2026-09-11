import contextlib,json,sys,time,re
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import typhoon_service as s
from phimthai.models import local_model
s.CONFIG['TYPHOON_TRANSLATE_MODEL']=str(local_model('translate-th-en',verify=True))
s.CONFIG['TYPHOON_DEVICE']='cpu'
s.CONFIG['TYPHOON_CPU_THREADS']='6'
s.load_translation_model()
text=' '.join(f'รายการที่ {1000+i} วันนี้เราจะทดสอบโปรแกรมพิมพ์ด้วยเสียงภาษาไทยและภาษาอังกฤษ โปรแกรมทำงานในเครื่องของคุณ กรุณาตรวจข้อความก่อนนำไปใช้งาน' for i in range(1,26))+' เลขสุดท้ายคือ 719'
original=s._translate_chunk_loaded
chunks=[]
def chunk(part):
    chunks.append(part)
    return original(part)
s._translate_chunk_loaded=chunk
start=time.perf_counter()
result=s._translate_text_loaded(text)
report={'model':'Helsinki-NLP/opus-mt-th-en','input_tokens':len(s.TRANSLATION_TOKENIZER.encode(text)),'chunks':len(chunks),'max_chunk_tokens':max(map(lambda c:len(s.TRANSLATION_TOKENIZER.encode(c)),chunks)),'input_characters_preserved':re.sub(r'\s+','',text)==re.sub(r'\s+','',''.join(chunks)),'final_marker_719_present':'719' in result,'all_number_markers_present':all(str(1000+i) in result for i in range(1,26)),'processing_seconds':time.perf_counter()-start,'text':result,'scope':'Synthetic original Thai text for input coverage/output tail; not a translation quality benchmark'}
(ROOT / 'docs/evidence/translation-long-short-segments.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='text'}),flush=True)

if not (report['input_characters_preserved'] and report['final_marker_719_present'] and report['all_number_markers_present']):
    raise SystemExit(1)
