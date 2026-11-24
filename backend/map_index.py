import json
import sqlite3
import threading
import unicodedata
from contextlib import closing
from pathlib import Path

from .geocoder import QUALITY_LABELS, classify_quality
from .geojson_stream import stream_geojson


def normalized(value):
    text = unicodedata.normalize("NFD", str(value or ""))
    return " ".join("".join(c for c in text if unicodedata.category(c) != "Mn").upper().split())


class MapIndex:
    """Índice SQLite local para não enviar o GeoJSON municipal inteiro ao navegador."""

    def __init__(self, geocoder):
        self.geocoder = geocoder
        self._locks = {}
        self._guard = threading.Lock()

    def _paths(self, job_id):
        source = self.geocoder.full_map_path(job_id)
        return source, source.with_name("mapa_territorial_v2.sqlite3")

    def ensure(self, job_id):
        source, target = self._paths(job_id)
        if target.exists() and target.stat().st_mtime >= source.stat().st_mtime: return target
        with self._guard: lock = self._locks.setdefault(job_id, threading.Lock())
        with lock:
            if target.exists() and target.stat().st_mtime >= source.stat().st_mtime: return target
            temp = target.with_suffix(".tmp")
            if temp.exists(): temp.unlink()
            with closing(sqlite3.connect(temp)) as db, db:
                db.executescript("""CREATE TABLE records(
                    id INTEGER PRIMARY KEY, cnpj TEXT, lon REAL, lat REAL, quality TEXT, score REAL,
                    precision TEXT, decision TEXT, name TEXT, street TEXT, number TEXT, neighborhood TEXT,
                    cnae TEXT, activity TEXT, n_cnpj TEXT, n_name TEXT, n_street TEXT, n_number TEXT,
                    n_neighborhood TEXT, n_activity TEXT, properties TEXT);
                    CREATE INDEX bbox_idx ON records(lon,lat); CREATE INDEX quality_idx ON records(quality);
                    CREATE INDEX cnpj_idx ON records(n_cnpj); CREATE INDEX score_idx ON records(score);
                    CREATE TABLE metadata(payload TEXT NOT NULL);""")
                rows=[]
                metadata={}
                for kind, feature in stream_geojson(source):
                    if kind == "metadata":
                        metadata = feature
                        continue
                    p=feature.get("properties", {}); coordinates=feature.get("geometry", {}).get("coordinates", [])
                    if len(coordinates)<2: continue
                    quality=classify_quality(p); p={**p,"quality":quality,"quality_label":QUALITY_LABELS[quality]}
                    name=p.get("nome_fantasia", ""); street=p.get("logradouro", ""); number=p.get("numero", ""); neighborhood=p.get("bairro", "")
                    cnae=str(p.get("cnae_fiscal_principal", "")); activity=str(p.get("cnae_principal_desc", ""))
                    rows.append((str(p.get("cnpj_completo", "")),coordinates[0],coordinates[1],quality,p.get("score_geocode"),p.get("precisao",""),p.get("decisao_geocode",""),name,street,number,neighborhood,cnae,activity,normalized(p.get("cnpj_completo")),normalized(name),normalized(street),normalized(number),normalized(neighborhood),normalized(activity),json.dumps(p,ensure_ascii=False,separators=(",",":"))))
                    if len(rows) >= 1000:
                        db.executemany("""INSERT INTO records(cnpj,lon,lat,quality,score,precision,decision,name,street,number,neighborhood,cnae,activity,n_cnpj,n_name,n_street,n_number,n_neighborhood,n_activity,properties) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
                        rows.clear()
                if rows:
                    db.executemany("""INSERT INTO records(cnpj,lon,lat,quality,score,precision,decision,name,street,number,neighborhood,cnae,activity,n_cnpj,n_name,n_street,n_number,n_neighborhood,n_activity,properties) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
                db.execute("INSERT INTO metadata(payload) VALUES(?)",(json.dumps(metadata,ensure_ascii=False),))
            temp.replace(target)
        return target

    def _connect(self, job_id):
        db=sqlite3.connect(self.ensure(job_id)); db.row_factory=sqlite3.Row; return db

    @staticmethod
    def _where(filters, bbox=None):
        parts=[]; values=[]
        if bbox:
            parts.append("lon BETWEEN ? AND ? AND lat BETWEEN ? AND ?"); values += [bbox[0],bbox[2],bbox[1],bbox[3]]
        qualities=filters.get("qualities")
        if qualities:
            q=qualities.split(","); parts.append("quality IN (%s)" % ",".join("?"*len(q))); values+=q
        for key,column in (("cnpj","n_cnpj"),("name","n_name"),("neighborhood","n_neighborhood")):
            if filters.get(key): parts.append(f"{column} LIKE ?"); values.append("%"+normalized(filters[key])+"%")
        if filters.get("street"):
            for term in normalized(filters["street"]).split(): parts.append("n_street LIKE ?"); values.append("%"+term+"%")
        if filters.get("number"): parts.append("n_number LIKE ?"); values.append(normalized(filters["number"])+"%")
        if filters.get("cnae"): parts.append("cnae LIKE ?"); values.append(normalized(filters["cnae"])+"%")
        if filters.get("activity"):
            for term in normalized(filters["activity"]).split(): parts.append("n_activity LIKE ?"); values.append("%"+term+"%")
        for key,op in (("score_min",">="),("score_max","<=")):
            if filters.get(key) not in (None,""): parts.append(f"score {op} ?"); values.append(float(filters[key]))
        if filters.get("precision"): parts.append("precision=?"); values.append(filters["precision"])
        if filters.get("decision"): parts.append("decision=?"); values.append(filters["decision"])
        if filters.get("selected"):
            ids=[x for x in filters["selected"].split(",") if x]; parts.append("cnpj IN (%s)" % ",".join("?"*len(ids))); values+=ids
        return (" WHERE "+" AND ".join(parts) if parts else ""),values

    @staticmethod
    def feature(row, light=False, map_only=False):
        properties=json.loads(row["properties"])
        if map_only:
            properties={key:properties.get(key) for key in ("cnpj_completo","nome_fantasia","quality") if key in properties}
        elif light:
            keep={"cnpj_completo","nome_fantasia","endereco_completo","logradouro","numero","bairro",
                  "score_geocode","decisao_geocode","necessita_revisao","precisao","desvio_metros",
                  "qtd_candidatos","geocode_status","quality","quality_label"}
            properties={key:value for key,value in properties.items() if key in keep}
        return {"type":"Feature","geometry":{"type":"Point","coordinates":[row["lon"],row["lat"]]},"properties":properties}

    def summary(self, job_id):
        with closing(self._connect(job_id)) as db:
            raw=json.loads(db.execute("SELECT payload FROM metadata").fetchone()[0]); bounds=db.execute("SELECT MIN(lon),MIN(lat),MAX(lon),MAX(lat) FROM records").fetchone()
            mapped=db.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            quality={key:0 for key in ("high","alert","review","unknown")}
            for key,count in db.execute("SELECT quality,COUNT(*) FROM records GROUP BY quality"):
                quality[key if key in quality else "unknown"] += count
            without=int(raw.get("without_coordinates",raw.get("total_sem_coordenada",0)) or 0)
            metadata={**raw,
                      "total_records":int(raw.get("total_records",raw.get("total_registros_csv",mapped+without)) or mapped+without),
                      "mapped":mapped,"without_coordinates":without,"quality":quality}
            precisions=[r[0] for r in db.execute("SELECT DISTINCT precision FROM records WHERE precision<>'' ORDER BY precision")]
            decisions=[r[0] for r in db.execute("SELECT DISTINCT decision FROM records WHERE decision<>'' ORDER BY decision")]
        return {"metadata":metadata,"bounds":list(bounds),"precisions":precisions,"decisions":decisions}

    def viewport(self, job_id, bbox, zoom, filters, reviewed=None, review_state=None):
        where,values=self._where(filters,bbox)
        with closing(self._connect(job_id)) as db:
            if review_state:
                raw=db.execute(f"SELECT lon,lat,properties,quality FROM records{where} LIMIT 50000",values).fetchall()
                wanted=review_state=="reviewed"; raw=[r for r in raw if (json.loads(r["properties"]).get("cnpj_completo") in reviewed)==wanted]
                if zoom < 15:
                    cell=max(0.00015,360/(2**zoom)*0.18); groups={}
                    for r in raw:
                        key=(int(r["lon"]/cell),int(r["lat"]/cell));g=groups.setdefault(key,{"lon":0,"lat":0,"point_count":0,"high":0,"alert":0,"review":0,"unknown":0});g["lon"]+=r["lon"];g["lat"]+=r["lat"];g["point_count"]+=1;g[r["quality"] if r["quality"] in {"high","alert","review","unknown"} else "unknown"]+=1
                    features=[{"type":"Feature","geometry":{"type":"Point","coordinates":[g["lon"]/g["point_count"],g["lat"]/g["point_count"]]},"properties":{"cluster":True,**{k:g[k] for k in ("point_count","high","alert","review","unknown")}}} for g in groups.values()]
                else: features=[self.feature(r, map_only=True) for r in raw[:10000]]
            elif zoom < 15:
                cell=max(0.00015,360/(2**zoom)*0.18)
                sql=f"""SELECT AVG(lon) lon,AVG(lat) lat,COUNT(*) point_count,
                    SUM(quality='high') high,SUM(quality='alert') alert,SUM(quality='review') review,SUM(quality='unknown') unknown
                    FROM records{where} GROUP BY CAST(lon/? AS INT),CAST(lat/? AS INT) LIMIT 4000"""
                rows=db.execute(sql,values+[cell,cell]).fetchall()
                features=[{"type":"Feature","geometry":{"type":"Point","coordinates":[r["lon"],r["lat"]]},"properties":{"cluster":True,**{k:r[k] for k in ("point_count","high","alert","review","unknown")}}} for r in rows]
            else:
                rows=db.execute(f"SELECT lon,lat,properties FROM records{where} LIMIT 10000",values).fetchall(); features=[self.feature(r, map_only=True) for r in rows]
        return {"type":"FeatureCollection","features":features}

    def records(self, job_id, filters, page=1, page_size=120, reviewed=None, review_state=None):
        where,values=self._where(filters); offset=max(0,page-1)*page_size
        with closing(self._connect(job_id)) as db:
            if review_state:
                candidates=db.execute(f"SELECT lon,lat,properties FROM records{where} ORDER BY name,cnpj",values).fetchall();wanted=review_state=="reviewed"; candidates=[r for r in candidates if (json.loads(r["properties"]).get("cnpj_completo") in reviewed)==wanted];total=len(candidates);rows=candidates[offset:offset+page_size]
            else:
                total=db.execute(f"SELECT COUNT(*) FROM records{where}",values).fetchone()[0]
                rows=db.execute(f"SELECT lon,lat,properties FROM records{where} ORDER BY name,cnpj LIMIT ? OFFSET ?",values+[page_size,offset]).fetchall()
        return {"total":total,"page":page,"page_size":page_size,"features":[self.feature(r, light=True) for r in rows]}

    def suggestions(self, job_id, field, query):
        columns={"cnpj":("cnpj","n_cnpj"),"name":("name","n_name"),"street":("street","n_street"),"activity":("activity","n_activity")}
        value_col,norm_col=columns[field]; terms=normalized(query).split(); where=" AND ".join(f"{norm_col} LIKE ?" for _ in terms)
        with closing(self._connect(job_id)) as db:
            rows=db.execute(f"SELECT lon,lat,properties FROM records WHERE {where} GROUP BY {value_col},neighborhood ORDER BY CASE WHEN {norm_col}=? THEN 0 WHEN {norm_col} LIKE ? THEN 1 ELSE 2 END,{value_col} LIMIT 10",[*("%"+t+"%" for t in terms),normalized(query),normalized(query)+"%"] ).fetchall()
        return [self.feature(r) for r in rows]

    def detail(self, job_id, cnpj):
        with closing(self._connect(job_id)) as db:
            row=db.execute("SELECT lon,lat,properties FROM records WHERE cnpj=? LIMIT 1",(str(cnpj),)).fetchone()
        return self.feature(row) if row else None

    def iter_features(self, job_id, filters):
        where,values=self._where(filters)
        db=self._connect(job_id)
        try:
            for row in db.execute(f"SELECT lon,lat,properties FROM records{where} ORDER BY id",values): yield self.feature(row)
        finally: db.close()
