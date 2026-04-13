
# from app.process import normalize_line
# from app.process import normalize_line, get_model_and_tokenizer
# from app import app
#
# with app.app_context():
#     model, tokenizer = get_model_and_tokenizer()
# print(normalize_line("""ione laloy desiuis.:Qins aoroient ⁊ leruoient
# les ydoles ⁊si feisoient faire ymages demeintes
# camblances ou il auoient lor fiance. ⁊ si creoiẽt
# eneles. ne autre diu naoroient ⁊totes les ma
# res auentures ⁊toutes les oeures qi adeu desplei
# soient estoient encel tenz ꝑles genz deces con
# trees aemplies. Qant mes sires sains march
# libencoiz euuangelistes uint en la terre. il
# trest aune cite qi estoit apelee cyrene.ou il
# troua genz nees del pais qi auques enten
# doient abien depluiseurs choses. Il les cou
# menca apreechier ⁊asermoner ⁊amonest̾
# la uoie desalu ⁊ꝑson seul sermon ⁊ꝑsa
# pole sauoit il pluiseurs enfers qi estoient
# entrepris degranz enfermetez.⁊si garissoit
# les meziaus.⁊si chacoit les deables fors des
# cors as homes ⁊as femes ꝑla grace de nostre sig
# nor.Lipluisor deceus del pais crurent en""", model, tokenizer))

full_text = """ione laloy desiuis.:Qins aoroient ⁊ leruoient
les ydoles ⁊si feisoient faire ymages demeintes
camblances ou il auoient lor fiance. ⁊ si creoiẽt
eneles. ne autre diu naoroient ⁊totes les ma
res auentures ⁊toutes les oeures qi adeu desplei
soient estoient encel tenz ꝑles genz deces con
trees aemplies. Qant mes sires sains march
libencoiz euuangelistes uint en la terre. il
trest aune cite qi estoit apelee cyrene.ou il
troua genz nees del pais qi auques enten
doient abien depluiseurs choses. Il les cou
menca apreechier ⁊asermoner ⁊amonest̾
la uoie desalu ⁊ꝑson seul sermon ⁊ꝑsa
pole sauoit il pluiseurs enfers qi estoient
entrepris degranz enfermetez.⁊si garissoit
les meziaus.⁊si chacoit les deables fors des
cors as homes ⁊as femes ꝑla grace de nostre sig
nor.Lipluisor deceus del pais crurent en"""
full_reg = """ione la loi des iuis ains aoroient et largioient les ydeles et si fesoient faire ymages de maintes semblances o il auoient lor fiances et si creoient en eles ne autre deu naoroient et totes les manres auentures et totes les oures qui a deu desplaisoient estoient en celui tans par les gens de ces contrees aemplies Quant mes sires sains march li banicois euangelistes uint en la terre il traist a une cite qui estoit apelee cyrene o il troua gens nees dou pais qui auques entendoient a bien de pluisors choses il les comensa a proecier et a sermoner et amonester la uoie de salu et par son soul sermon et par sa parole sauoit il pluisors enfers qui estoient entrepris de grans enfermetes et si guarissoit les mesiaus et si chassoit les deables fors des cors as homes et as femes par la grace de nnostre ssegnor Li pluisor de ceaus dou pais criurent en """

from app.annot_utils import align_to_annotations
from app.alignment import align_words
print(align_words(full_text, full_reg))