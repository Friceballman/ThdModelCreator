"""Assemble immutable local review GIFs and an index from verified Blender renders."""
from pathlib import Path
import hashlib,json,os,sys,uuid
from urllib.parse import quote
from PIL import Image,ImageDraw,ImageFont
project=Path('projects/e2fbd0be-7077-4411-aab9-62fa8ce06c80').resolve();case=project/'planning/rigging-v35-20261023'
model_run,preview_run=sys.argv[1:3];model=project/'runs'/model_run/'outputs/model.blend';source=project/'runs'/preview_run/'outputs'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
plan=json.loads((source.parent/'plan.json').read_text(encoding='utf-8'));assert plan['source_hash']==sha(model)
data=json.loads((source/'checks.json').read_text(encoding='utf-8'));assert data['success']
output=case/('review-'+str(uuid.uuid4()));output.mkdir()
font=ImageFont.truetype('C:/Windows/Fonts/meiryo.ttc',20)
small=ImageFont.truetype('C:/Windows/Fonts/meiryo.ttc',14)
labels={'01_Idle':'待機','02_Walk':'歩行','03_Run':'走行','04_Hit_Recoil':'被弾・のけ反り','05_Knockback':'吹き飛び'}
cards=[]
for clip in data['clips']:
    name=clip['name'];frames=clip['frames'];gif_frames=[]
    selected=frames[:-1] if name in ['01_Idle','02_Walk','03_Run'] else frames
    for frame in selected:
        canvas=Image.new('RGB',(1024,552),(24,28,35));draw=ImageDraw.Draw(canvas)
        draw.text((16,8),f'{labels[name]}    {name}    frame {frame:02} / {frames[-1]}',font=font,fill=(245,245,245))
        for x,view in [(0,'side'),(512,'oblique')]:
            with Image.open(source/name/f'f{frame:03}-{view}.png') as im:canvas.paste(im.convert('RGB'),(x,40))
        gif_frames.append(canvas)
    durations=[round((i+1)*100/15)*10-round(i*100/15)*10 for i in range(len(gif_frames))]
    if name in ['04_Hit_Recoil','05_Knockback']:durations[-1]+=500
    palette=gif_frames[0].quantize(colors=192)
    encoded=[im.quantize(palette=palette,dither=Image.Dither.NONE) for im in gif_frames]
    gif=output/f'{name}.gif';encoded[0].save(gif,save_all=True,append_images=encoded[1:],duration=durations,loop=0,optimize=False,disposal=2)
    with Image.open(gif) as check:assert check.n_frames==len(encoded),(name,check.n_frames,len(encoded))
    sheet=Image.new('RGB',(1024,148*((len(frames)+3)//4)),(24,28,35));draw=ImageDraw.Draw(sheet)
    for i,frame in enumerate(frames):
        x=(i%4)*256;y=(i//4)*148
        for dx,view in [(0,'side'),(128,'oblique')]:
            with Image.open(source/name/f'f{frame:03}-{view}.png') as im:sheet.paste(im.convert('RGB').resize((128,128)),(x+dx,y+20))
        draw.text((x+4,y),f'{name} f{frame:03}',font=small,fill=(245,245,245))
    sheet.save(output/f'{name}-all-frames.png')
    keys=sorted({frames[0],frames[len(frames)//4],frames[len(frames)//2],frames[3*len(frames)//4],frames[-1]})
    multi=Image.new('RGB',(len(keys)*216,4*240),(24,28,35));draw=ImageDraw.Draw(multi)
    for r,view in enumerate(['front','side','back','oblique']):
        for c,frame in enumerate(keys):
            with Image.open(source/name/f'f{frame:03}-{view}.png') as im:multi.paste(im.convert('RGB').resize((216,216)),(c*216,r*240+24))
            draw.text((c*216+4,r*240+3),f'{view} f{frame:03}',font=small,fill=(245,245,245))
    multi.save(output/f'{name}-four-views.png')
    cards.append(f'<section><h2>{labels[name]}</h2><img src="{gif.name}" alt="{labels[name]}の側面・斜めからの確認用アニメーション"><p><code>{name}</code>：1–{frames[-1]}フレーム、元データ30fps。GIFは15fps。<a href="{name}-four-views.png">四方向の代表フレーム</a> · <a href="{name}-all-frames.png">全プレビューフレーム</a></p></section>')
def link(p):return quote(os.path.relpath(p,output).replace('\\','/'),safe='/')
html='''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>リグ・動作確認 ver3.5</title><style>body{margin:0;background:#11151c;color:#edf0f6;font:16px/1.7 Meiryo,sans-serif}main{max-width:1080px;margin:auto;padding:28px}a{color:#8fd1ff}h1{font-size:28px}h2{font-size:22px}section{margin:28px 0;padding:20px;background:#202631;border-radius:10px}img{width:100%;height:auto;display:block}code{color:#d8e6ff}.tag{background:#364258;padding:6px 12px;border-radius:6px}li{margin:8px 0}</style><main><h1>リグ・動作確認 ver3.5</h1><p class="tag">確認用の5動作 · UE実機未確認 · 正式採用は未実施</p>'''
html+=f'<p><a href="{link(model)}">編集可能なBlenderモデル</a> · <a href="{link(model.parent/"fbx")}">FBX一式</a> · <a href="artifact-manifest.json">ファイルと元モデルの対応</a></p>'
html+='<p>モデルを開くと待機Actionが選択されています。スペースキーで再生できます。別の動作はAction Editorで選択し、終了フレームを下記の範囲に合わせてください。<code>00_Source_Pose</code>は元の静止ポーズへ戻すActionです。</p><p>歩行・走行はその場再生です。吹き飛びはrootが後方へ移動し、GIFの繰り返し時に開始位置へ戻ります。被弾・吹き飛びのGIF末尾には確認用の停止時間があります。</p>'
html+=''.join(cards)+'</main></html>'
(output/'index.html').write_text(html,encoding='utf-8')
manifest=dict(kind='rigging_validation_review',project_id=project.name,source_static_candidate_id='47dab7b4-5ba2-4702-be3f-ec2ffe6ea04c',requirement_id='1c648bc9-a7ed-4a8b-b559-e49948146080',
    model_run=model_run,model_path=model.relative_to(project).as_posix(),model_sha256=sha(model),preview_run=preview_run,preview_model_source_hash=plan['source_hash'],
    ue_verified=False,formal_adoption=False,visual_review='pending',clips=data['clips'],
    files=[dict(path=p.name,sha256=sha(p),bytes=p.stat().st_size) for p in sorted(output.iterdir())])
(output/'artifact-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
(case/f'review-{model_run}-context.json').write_text(json.dumps(dict(directory=output.relative_to(project).as_posix(),model_run=model_run,preview_run=preview_run),indent=2),encoding='utf-8')
print(json.dumps(dict(review=output.relative_to(project).as_posix(),files=len(manifest['files'])),ensure_ascii=True))
