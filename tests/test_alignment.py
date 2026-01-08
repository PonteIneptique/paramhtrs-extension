from app.aligner import global_align


def test_alignment():
    inputs = [
        dict(raw="faison e bonne chere et noel chanten Noel chanton et faison"
                 " bonne chere En saluant lle fih drou et sa mere O noel chanton "
                 "faisons bonne chere et chanton nol Sa naissanto ne fut onques amere "
                 "En terre na oucle mepnen ne pere O noel chanton faison bonne chere et"
                 " chanton mocl A dam qui fist contre luy uitupere fut Rachete de Redemyeroñ "
                 "chere Onoel chanton faison bonne chere et chanton noel Iehan uint "
                 "deuant uesta de poure hane qui du mori de Remonstra la misere o noel"
                 " chanton faison bonure ehere et chanton nos Ihne apres aohena le mistere "
                 "sa passion nous est atons notorre Onoel chanton faison bonno chere et noel"
                 " chanton Puis ⁊l luy plent Resmection faire dont centy des limbes auorent"
                 " trespit affi Curel chanton",
             reg="faisons bone chere et noel chanton. Noel chanton et faisons"
                " bone chere, en saluant il, fil Dieu et sa mere, O Noel chanton "
                "faisons bone chere et chanton noel. Sa naissance ne fut onques amere "
                "en terre n'a oncle merveil ne pere. O Noel chanton faisons bone chere et"
                " chanton noel. Adam qui fist contre lui vitupere fut racheté de redemption "
                "chere. O Noel chanton faisons bone chere et chanton noel. Jehan vint "
                "devant veste de povre Haine, qui du mort demonstra la misere. O Noel"
                " chanton faisons bone chere et chanton noel. Jehan aprés adherent le mistere, "
                "sa passion nous est atous notoire. O Noel chanton faisons bone chere et noel"
                " chanton. Puis il lui plent resmection faire dont cent des limbes avorent"
                " trespit affin. O Noel chanton",
             gt=[
            ('faison e', 'faisons'), (' ', ' '), ('bonne', 'bone'), (' ', ' '), ('chere', 'chere'), (' ', ' '),
            ('et', 'et'), (' ', ' '), ('noel', 'noel'), (' ', ' '), ('chanten', 'chanton.'), (' ', ' '),
            ('Noel', 'Noel'), (' ', ' '), ('chanton', 'chanton'), (' ', ' '), ('et', 'et'), (' ', ' '),
            ('faison', 'faisons'), (' ', ' '), ('bonne', 'bone'), (' ', ' '), ('chere', 'chere,'), (' ', ' '),
            ('En', 'en'), (' ', ' '), ('saluant', 'saluant'), (' ', ' '), ('lle', 'il,'), (' ', ' '),
            ('fih', 'fil'), (' ', ' '), ('drou', 'Dieu'), (' ', ' '), ('et', 'et'), (' ', ' '), ('sa', 'sa'),
            (' ', ' '), ('mere', 'mere,'), (' ', ' '), ('O', 'O'), (' ', ' '), ('noel', 'Noel'), (' ', ' '),
            ('chanton', 'chanton'), (' ', ' '), ('faisons', 'faisons'), (' ', ' '), ('bonne', 'bone'), (' ', ' '),
            ('chere', 'chere'), (' ', ' '), ('et', 'et'), (' ', ' '), ('chanton', 'chanton'), (' ', ' '),
            ('nol', 'noel.'), (' ', ' '), ('Sa', 'Sa'), (' ', ' '), ('naissanto', 'naissance'), (' ', ' '),
            ('ne', 'ne'), (' ', ' '), ('fut', 'fut'), (' ', ' '), ('onques', 'onques'), (' ', ' '),
            ('amere', 'amere'), (' En ', ' en '), ('terre', 'terre'), (' ', ' '), ('na', "n'a"), (' ', ' '),
            ('oucle', 'oncle'), (' ', ' '), ('mepnen', 'merveil'), (' ', ' '), ('ne', 'ne'), (' ', ' '),
            ('pere', 'pere.'), (' ', ' '), ('O', 'O'), (' ', ' '), ('noel', 'Noel'), (' ', ' '),
            ('chanton', 'chanton'), (' ', ' '), ('faison', 'faisons'), (' ', ' '), ('bonne', 'bone'), (' ', ' '),
            ('chere', 'chere'), (' ', ' '), ('et', 'et'), (' ', ' '), ('chanton', 'chanton'), (' ', ' '),
            ('mocl', 'noel.'), (' ', ' '), ('A dam', 'Adam'), (' ', ' '), ('qui', 'qui'), (' ', ' '),
            ('fist', 'fist'), (' ', ' '), ('contre', 'contre'), (' ', ' '), ('luy', 'lui'), (' ', ' '),
            ('uitupere', 'vitupere'), (' ', ' '), ('fut', 'fut'), (' ', ' '), ('Rachete', 'racheté'), (' ', ' '),
            ('de', 'de'), (' ', ' '), ('Redemyeroñ', 'redemption'), (' ', ' '), ('chere', 'chere.'), (' ', ' '),
            ('Onoel', 'O Noel'), (' ', ' '), ('chanton', 'chanton'), (' ', ' '), ('faison', 'faisons'), (' ', ' '),
            ('bonne', 'bone'), (' ', ' '), ('chere', 'chere'), (' ', ' '), ('et', 'et'), (' ', ' '),
            ('chanton', 'chanton'), (' ', ' '), ('noel', 'noel.'), (' ', ' '), ('Iehan', 'Jehan'), (' ', ' '),
            ('uint', 'vint'), (' ', ' '), ('deuant', 'devant'), (' ', ' '), ('uesta', 'veste'), (' ', ' '),
            ('de', 'de'), (' ', ' '), ('poure', 'povre'), (' ', ' '), ('hane', 'Haine,'), (' ', ' '),
            ('qui', 'qui'), (' ', ' '), ('du', 'du'), (' ', ' '), ('mori', 'mort'), (' ', ' '),
            ('de Remonstra', 'demonstra'), (' ', ' '), ('la', 'la'), (' ', ' '), ('misere', 'misere.'), (' ', ' '),
            ('o', 'O'), (' ', ' '), ('noel', 'Noel'), (' ', ' '), ('chanton', 'chanton'), (' ', ' '),
            ('faison', 'faisons'), (' ', ' '), ('bonure', 'bone'), (' ', ' '), ('ehere', 'chere'), (' ', ' '),
            ('et', 'et'), (' ', ' '), ('chanton', 'chanton'), (' ', ' '), ('nos', 'noel.'), (' ', ' '),
            ('Ihne', 'Jehan'), (' ', ' '), ('apres', 'aprés'), (' ', ' '), ('aohena', 'adherent'), (' ', ' '),
            ('le', 'le'), (' ', ' '), ('mistere', 'mistere,'), (' ', ' '), ('sa', 'sa'), (' ', ' '),
            ('passion', 'passion'), (' ', ' '), ('nous', 'nous'), (' ', ' '), ('est', 'est'), (' ', ' '),
            ('atons', 'atous'), (' ', ' '), ('notorre', 'notoire.'), (' ', ' '), ('Onoel', 'O Noel'), (' ', ' '),
            ('chanton', 'chanton'), (' ', ' '), ('faison', 'faisons'), (' ', ' '), ('bonno', 'bone'), (' ', ' '),
            ('chere', 'chere'), (' ', ' '), ('et', 'et'), (' ', ' '), ('noel', 'noel'), (' ', ' '),
            ('chanton', 'chanton.'), (' ', ' '), ('Puis', 'Puis'), (' ', ' '), ('⁊l', 'il'), (' ', ' '),
            ('luy', 'lui'), (' ', ' '), ('plent', 'plent'), (' ', ' '), ('Resmection', 'resmection'), (' ', ' '),
            ('faire', 'faire'), (' ', ' '), ('dont', 'dont'), (' ', ' '), ('centy', 'cent'), (' ', ' '),
            ('des', 'des'), (' ', ' '), ('limbes', 'limbes'), (' ', ' '), ('auorent', 'avorent'), (' ', ' '),
            ('trespit', 'trespit')]),
        dict(
            raw="Qrto decimo gͥ anno scđo pͥ neronẽ ꝑ secutionẽ mouẽte do mitiano. ioħs inpathmos insula relegatꝰ scͥpsit apocalipsin. Intfecto aut̃ domĩtia no a senaturo mano rediit ad ephesũ. ibiqꝙ usq ad traianũ pͥncipẽ ꝑ seuerans totius asie fundauit ⁊ rexit eccłias. Et c̃fectus senio. sexage simõ .uiͦi. pͦ passionẽ dñi anno. ęcatũ aut̃ suꝑ nonagesimo nono mor- tuns. ẽ: ac uxta eandẽ ur̃bẽ sepultꝰ.",
            reg="rto decimo igitur anno secundo post Neronem persecutionem movente Domitiano, Joannes in Pathmos insulam relegatus scripsit Apocalypsim. Interfecto autem Domitiano a senatu Romano, rediit ad Ephesum, ibique usque ad Trajanum principem perseverans, totius Asiae fundavit et rexit Ecclesias. Et confectus senio, sexagesimo septimo post passionem Domini anno, aetatum autem super nonagesimo nono mortuus est, ac juxta eamdem urbem sepultus. ",
            gt=[
                ('Qrto', 'rto'), (' ', ' '), ('decimo', 'decimo'), (' ', ' '), ('gͥ', 'igitur'), (' ', ' '),
                ('anno', 'anno'), (' ', ' '), ('scđo', 'secundo'), (' ', ' '), ('pͥ', 'post'), (' ', ' '),
                ('neronẽ', 'Neronem'), (' ', ' '), ('ꝑ secutionẽ', 'persecutionem'), (' ', ' '),
                ('mouẽte', 'movente'), (' ', ' '), ('do mitiano.', 'Domitiano,'), (' ', ' '), ('ioħs', 'Joannes'),
                (' ', ' '), ('inpathmos', 'in Pathmos'), (' ', ' '), ('insula', 'insulam'), (' ', ' '),
                ('relegatꝰ', 'relegatus'), (' ', ' '), ('scͥpsit', 'scripsit'), (' ', ' '),
                ('apocalipsin.', 'Apocalypsim.'), (' ', ' '), ('Intfecto', 'Interfecto'), (' ', ' '), ('aut̃', 'autem'),
                (' ', ' '), ('domĩtia no', 'Domitiano'), (' ', ' '), ('a', 'a'), (' ', ' '),
                ('senaturo mano', 'senatu Romano,'), (' ', ' '), ('rediit', 'rediit'), (' ', ' '), ('ad', 'ad'),
                (' ', ' '), ('ephesũ.', 'Ephesum,'), (' ', ' '), ('ibiqꝙ\uf1ac', 'ibique'), (' ', ' '),
                ('usq\uf1ac', 'usque'), (' ', ' '), ('ad', 'ad'), (' ', ' '), ('traianũ', 'Trajanum'), (' ', ' '),
                ('pͥncipẽ', 'principem'), (' ', ' '), ('ꝑ seuerans', 'perseverans,'), (' ', ' '), ('totius', 'totius'),
                (' ', ' '), ('asie', 'Asiae'), (' ', ' '), ('fundauit', 'fundavit'), (' ', ' '), ('⁊', 'et'),
                (' ', ' '), ('rexit', 'rexit'), (' ', ' '), ('eccłias.', 'Ecclesias.'), (' ', ' '), ('Et', 'Et'),
                (' ', ' '), ('c̃fectus', 'confectus'), (' ', ' '), ('senio.', 'senio,'), (' ', ' '),
                ('sexage simõ', 'sexagesimo'), (' ', ' '), ('.uiͦi.', 'septimo'), (' ', ' '), ('pͦ', 'post'),
                (' ', ' '), ('passionẽ', 'passionem'), (' ', ' '), ('dñi', 'Domini'), (' ', ' '), ('anno.', 'anno,'),
                (' ', ' '), ('ęcatũ', 'aetatum'), (' ', ' '), ('aut̃', 'autem'), (' ', ' '), ('suꝑ', 'super'),
                (' ', ' '), ('nonagesimo', 'nonagesimo'), (' ', ' '), ('nono', 'nono'), (' ', ' '),
                ('mor- tuns.', 'mortuus'), (' ', ' '), ('ẽ:', 'est,'), (' ', ' '), ('ac', 'ac')])
    ]

    for el in inputs:
        assert global_align(el["raw"], el["reg"]) == el["gt"]


print(test_alignment())
