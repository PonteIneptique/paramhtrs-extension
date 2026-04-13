from app.alignment import Alignment
from app.alignment import align_words


# Rules for alignment
# 1. code[n] should not follow each other: if multiple things (punctuation, tokens, spaces, etc.) are null operations
#       then they form a single Alignment: `a b c` -> `a b c`: Alignment(source='a b c', target='a b c', code='n')
# 2. Changes in tokens are moved into a code[s]: Alignment(source='REATOR', target='reator', code='s')
# 3. Changes in punctuation are moved into a code[s]: Alignment(source='.', target=',', code='s')
# 4. Two edge cases exist for 2+3:
#    4.1. `casa.`->`casa,` is a null operation on casa Alignment(source='casa', target='casa', code='n')
#       and a substitution on ,/.
#    4.2  `.n.` -> `enim` is a full code[n] in a single step because dots here are
#       deleted: Alignment(source='.n.', target='enim', code='s'). Same goes for `G.` -> `Galienus`
#       Alignment(source='G.', target='Galienus', code='s')
# 5. If a token deletion is followed by a token insertion, it's most likely a substitution.
# 6. Space insertion is a specific kind of phenomenon that needs to be captured `ab`-> `a b`: a[code = n]
#       Alignment(source='', target=' ', code='i') b[code = n]
# 7. Space deletion leads to a single token most of the time, except before punctuation
#       7.1 `a b` -> `ab`: Alignment(source="a b", target="ab", code="s")
#       7.2 `a .` -> `a.`: [Alignment(source="a", target="a", code="n"),
#                           Alignment(source=" ", target="", code="d")
#                           Alignment(source=".", target=".", code="n")]


def test_alignment_rules():
    """
    Tests the alignment logic against the 7 core business rules provided.
    """
    test_cases = [
        # Rule 1: Consecutive null operations merge
        ("a b c", "a b c", [Alignment("a b c", "a b c", "n")]),

        # Rule 2: Token changes are substitutions
        ("REATOR", "reator", [Alignment("REATOR", "reator", "s")]),

        # Rule 3: Punctuation changes are substitutions
        (".", ",", [Alignment(".", ",", "s")]),

        # Rule 4.1: Mixed match and punctuation substitution
        ("casa.", "casa,", [
            Alignment("casa", "casa", "n"),
            Alignment(".", ",", "s")
        ]),

        # Rule 4.2: Abbreviations/deletions within tokens are single substitutions
        (".n.", "enim", [Alignment(".n.", "enim", "s")]),
        ("G.", "Galienus", [Alignment("G.", "Galienus", "s")]),

        # Rule 5: Deletion + Insertion = Substitution
        # (Assuming the engine interprets 'old' -> 'new' as 's' rather than 'd' then 'i')
        ("word", "verb", [Alignment("word", "verb", "s")]),

        # Rule 6: Space insertion (Special 'i' case)
        ("ab", "a b", [
            Alignment("a", "a", "n"),
            Alignment("", " ", "i"),
            Alignment("b", "b", "n")
        ]),

        # Rule 7.1: Space deletion in tokens
        ("a b", "ab", [Alignment("a b", "ab", "s")]),

        # Rule 7.2: Space deletion before punctuation
        ("a .", "a.", [
            Alignment("a", "a", "n"),
            Alignment(" ", "", "d"),
            Alignment(".", ".", "n")
        ])
    ]

    for source, target, expected in test_cases:
        # Replace 'align_function' with your actual implementation call
        result = align_words(source, target)
        assert result == expected, f"Failed Rule Alignment for: {source} -> {target}"

def test_long_latin():
    abbr = """REATOR UOENS animaliũ gꝰ firmit̾ ꝑman̾e ⁊ ñ ꝑire : ꝑ coitũ illiꝰ gen̾atio̾ẽ disposuit renouari. ut renouatũ ĩt̾itũ ex toto ñ haberet. Ideoq c̾plasmauit ai̾alibꝰ m̃bra natͣlia q̃ ad ħ opꝰ apta forent ⁊ ꝓͥa. eiꝰq tã mirabilẽ delectatio̾ẽ ĩseruit u̇ nullũ sit ai̾al qd ñ ꝑ coitũ nimiũ delectet᷑. Nã si ai̾alia coitũ odirent: ai̾aliũ genꝰ ꝓ c̾co ꝑiret. In tantũ .N. nat᷑alr̾ ĩẽ. coitꝰ. u̇ ꝑ multa tẽporͣ ĩpeditꝰ ẽ expellendi possi bilitaᷤᷤ adfu̾it oĩ pene ro̾e pꝰposita. fiat coitꝰ ꝑ duo ai̾alia. ꝑ unũ .N. sem̃ emitit᷑. cui aliud obuiando ĩ sua ꝓfundiͣtate ꝯcauitate : illud recip̃ un̾diq ne ex aliqͣ parte possit diffundi.⁊ disꝑgi. Ria s̃ in coitu. Appetitꝰ ex cogitatiõe fantastica ortꝰ.⁊ sp̃s. ⁊ hũor. Ap petitꝰ ab epate. sp̃s a corde. Hũor a c̾ebro. Nã cũ delectabit sp̃s motꝰ sit ĩ coitu ꝑ motũ. oĩa m̃b ͣ corꝑriᷤᷤ ꝯuͣeltᷤᷤcunt ⁊ ꝑ calorẽ eliqͣt᷑ hũor qͥ ẽ.ĩ ce̾b ͦ ⁊ eliqͣtꝰ attͣhit᷑ ꝑ uenaᷤᷤ q̃ pꝰ aureᷤᷤ ducunt᷑ ad testiculoᷤᷤ. ⁊ in̾ ꝑ uͥga ĩ uuluã eicit᷑. Nã u̇ ypoc̾s dic̃ qͥbꝰc̾q uene q̃ pꝰ aureᷤᷤ ducunt᷑ excuse fu̾int femine ñ fuso : gign̾e ñ p̃ualent. Si uͦ aliqͥd emiserint. unitꝰ sem̃.s. aqͦsꝰ hu. un̾ nullꝰ ꝯceptꝰ"""
    reg = """reator volens animalium genus firmiter permanere et non perire, per coitum illius generacionem disposuit renovari, ut renovatum interitum ex toto non haberet. Ideoque complasmavit animalibus membra naturalia quod ad hoc opus apta forent et propria, eiusque tam mirabilem delectacionem inseruit ut nullum sit animalium quod non per coitum nimium delectetur. Nam si animalia coitum odirent, animalium genus pro certo periret. In tantum enim naturaliter inest coitus. ut per multa tempora impeditus, cum expellendi possibilitas affuerit, omni pene racione postposita. fiat coitus per duo animalia, per unum enim semen emittitur, cui aliud obviando in sua profunditate concavitate illud recipit undique ne ex aliqua parte possit diffundi. et dispergi. Tria sunt in coitu: appetitus ex cogitacione fantastica ortus, et spiritus et humor. Appetitus ab epate, spiritus a corde, humor a cerebro; nam cum delectabilitur spiritus motus sit in coitu, per motum omnia membra corporis convalescunt et per calorem eliquatur humor qui est in cerebro, et eliquatus attrahitur per venas que post aures ducuntur ad testiculos, et inde per virgam in vulvam eicitur. Nam ut Ypocras dicit: quibuscumque vene que post aures ducuntur excise fuerint, semine non fuso, gignere non prevalent. Si vero aliquid emiserint, unitus semen sed aquosus humor unde nullus conceptus"""
    expected = [
        Alignment(source='REATOR', target='reator', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='UOENS', target='volens', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='animaliũ', target='animalium', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='gꝰ', target='genus', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='firmit̾', target='firmiter', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝑman̾e', target='permanere', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='⁊', target='et', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ñ', target='non', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝑire', target='perire,', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source=': ꝑ', target='per', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='coitũ', target='coitum', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='illiꝰ', target='illius', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='gen̾atio̾ẽ', target='generacionem', code='s'),
        Alignment(source=' disposuit ', target=' disposuit ', code='n'),
        Alignment(source='renouari', target='renovari', code='s'),
        Alignment(source='.', target=',', code='s'),
        Alignment(source=' ut ', target=' ut ', code='n'),
        Alignment(source='renouatũ', target='renovatum', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ĩt̾itũ', target='interitum', code='s'),
        Alignment(source=' ex toto ', target=' ex toto ', code='n'),
        Alignment(source='ñ', target='non', code='s'),
        Alignment(source=' haberet. ', target=' haberet. ', code='n'),
        Alignment(source='Ideoq\uf1ac', target='Ideoque', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='c̾plasmauit', target='complasmavit', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ai̾alibꝰ', target='animalibus', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='m̃bra', target='membra', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='natͣlia', target='naturalia', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='q̃', target='quod', code='s'),
        Alignment(source=' ad ', target=' ad ', code='n'),
        Alignment(source='ħ', target='hoc', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='opꝰ', target='opus', code='s'),
        Alignment(source=' apta forent ', target=' apta forent ', code='n'),  # Non modification are glued
        Alignment(source='⁊', target='et', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝓͥa.', target='propria,', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='eiꝰq\uf1ac', target='eiusque', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='tã', target='tam', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='mirabilẽ', target='mirabilem', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='delectatio̾ẽ', target='delectacionem', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ĩseruit', target='inseruit', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='u̇', target='ut', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='nullũ', target='nullum', code='s'),
        Alignment(source=' sit ', target=' sit ', code='n'),
        Alignment(source='ai̾al', target='animalium', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='qd', target='quod', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ñ', target='non', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝑ', target='per', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='coitũ', target='coitum', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='nimiũ', target='nimium', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='delectet᷑', target='delectetur', code='s'),
        Alignment(source='. ', target='. ', code='n'),
        Alignment(source='Nã', target='Nam', code='s'),
        Alignment(source=' si ', target=' si ', code='n'),
        Alignment(source='ai̾alia', target='animalia', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='coitũ', target='coitum', code='s'),
        Alignment(source=' odirent', target=' odirent', code='n'),
        Alignment(source=':', target=',', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ai̾aliũ', target='animalium', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='genꝰ', target='genus', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝓ', target='pro', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='c̾co', target='certo', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝑiret', target='periret', code='s'),
        Alignment(source='. In ', target='. In ', code='n'),
        Alignment(source='tantũ', target='tantum', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='.N.', target='enim', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='nat᷑alr̾', target='naturaliter', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ĩẽ.', target='inest', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='coitꝰ', target='coitus', code='s'),
        Alignment(source='. ', target='. ', code='n'),
        Alignment(source='u̇', target='ut', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝑ', target='per', code='s'),
        Alignment(source=' multa ', target=' multa ', code='n'),
        Alignment(source='tẽporͣ', target='tempora', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ĩpeditꝰ', target='impeditus', code='s'),
        Alignment(source='', target=',', code='i'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='', target='cum', code='i'),
        Alignment(source='ẽ', target='', code='d'),
        Alignment(source=' expellendi ', target=' expellendi ', code='n'),
        Alignment(source='possi bilitaᷤᷤ', target='possibilitas', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='adfu̾it', target='affuerit,', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='oĩ', target='omni', code='s'),
        Alignment(source=' pene ', target=' pene ', code='n'),
        Alignment(source='ro̾e', target='racione', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='pꝰposita', target='postposita', code='s'),
        Alignment(source='. fiat ', target='. fiat ', code='n'),
        Alignment(source='coitꝰ', target='coitus', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝑ', target='per', code='s'),
        Alignment(source=' duo ', target=' duo ', code='n'),
        Alignment(source='ai̾alia', target='animalia', code='s'),
        Alignment(source='.', target=',', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝑ', target='per', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='unũ', target='unum', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='.N.', target='enim', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='sem̃', target='semen', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='emitit᷑.', target='emittitur,', code='s'),
        Alignment(source=' cui aliud ', target=' cui aliud ', code='n'),
        Alignment(source='obuiando', target='obviando', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ĩ', target='in', code='s'),
        Alignment(source=' sua ', target=' sua ', code='n'),
        Alignment(source='ꝓfundiͣtate', target='profunditate', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝯcauitate', target='concavitate', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source=': ', target='', code='d'),
        Alignment(source='illud ', target='illud ', code='n'),
        Alignment(source='recip̃', target='recipit', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='un̾diq\uf1ac', target='undique', code='s'),
        Alignment(source=' ne ex ', target=' ne ex ', code='n'),
        Alignment(source='aliqͣ', target='aliqua', code='s'),
        Alignment(source=' parte possit diffundi.', target=' parte possit diffundi.', code='n'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='⁊', target='et', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='disꝑgi', target='dispergi', code='s'),
        Alignment(source='. ', target='. ', code='n'),
        Alignment(source='Ria', target='Tria', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='s̃', target='sunt', code='s'),
        Alignment(source=' in coitu', target=' in coitu', code='n'),
        Alignment(source='.', target=':', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='Appetitꝰ', target='appetitus', code='s'),
        Alignment(source=' ex ', target=' ex ', code='n'),
        Alignment(source='cogitatiõe', target='cogitacione', code='s'),
        Alignment(source=' fantastica ', target=' fantastica ', code='n'),
        Alignment(source='ortꝰ', target='ortus', code='s'),
        Alignment(source='.', target=',', code='s'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='⁊', target='et', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='sp̃s.', target='spiritus', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='⁊', target='et', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='hũor', target='humor', code='s'),
        Alignment(source='. ', target='. ', code='n'),
        Alignment(source='Ap petitꝰ', target='Appetitus', code='s'),
        Alignment(source=' ab epate', target=' ab epate', code='n'),
        Alignment(source='.', target=',', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='sp̃s', target='spiritus', code='s'),
        Alignment(source=' a corde', target=' a corde', code='n'),
        Alignment(source='.', target=',', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='Hũor', target='humor', code='s'),
        Alignment(source=' a ', target=' a ', code='n'),
        Alignment(source='c̾ebro', target='cerebro', code='s'),
        Alignment(source='.', target=';', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='Nã', target='nam', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='cũ', target='cum', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='delectabit', target='delectabilitur', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='sp̃s', target='spiritus', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='motꝰ', target='motus', code='s'),
        Alignment(source=' sit ', target=' sit ', code='n'),
        Alignment(source='ĩ', target='in', code='s'),
        Alignment(source=' coitu', target=' coitu', code='n'),
        Alignment(source='', target=',', code='i'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝑ', target='per', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='motũ', target='motum', code='s'),
        Alignment(source='.', target='', code='d'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='oĩa', target='omnia', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='m̃b ͣ', target='membra', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='corꝑriᷤᷤ', target='corporis', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝯuͣeltᷤᷤcunt', target='convalescunt', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='⁊', target='et', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝑ', target='per', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='calorẽ', target='calorem', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='eliqͣt᷑', target='eliquatur', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='hũor', target='humor', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='qͥ', target='qui', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ẽ', target='est', code='s'),
        Alignment(source='.', target='', code='d'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='ĩ', target='in', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ce̾b ͦ', target='cerebro', code='s'),
        Alignment(source='', target=',', code='i'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='⁊', target='et', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='eliqͣtꝰ', target='eliquatus', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='attͣhit᷑', target='attrahitur', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝑ', target='per', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='uenaᷤᷤ', target='venas', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='q̃', target='que', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='pꝰ', target='post', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='aureᷤᷤ', target='aures', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ducunt᷑', target='ducuntur', code='s'),
        Alignment(source=' ad ', target=' ad ', code='n'),
        Alignment(source='testiculoᷤᷤ', target='testiculos', code='s'),
        Alignment(source='.', target=',', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='⁊', target='et', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='in̾', target='inde', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝑ', target='per', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='uͥga', target='virgam', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ĩ', target='in', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='uuluã', target='vulvam', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='eicit᷑', target='eicitur', code='s'),
        Alignment(source='. ', target='. ', code='n'),
        Alignment(source='Nã', target='Nam', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='u̇', target='ut', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ypoc̾s', target='Ypocras', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='dic̃', target='dicit:', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='qͥbꝰc̾q\uf1ac', target='quibuscumque', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='uene', target='vene', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='q̃', target='que', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='pꝰ', target='post', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='aureᷤᷤ', target='aures', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ducunt᷑', target='ducuntur', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='excuse', target='excise', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='fu̾int', target='fuerint', code='s'),
        Alignment(source='', target=',', code='i'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='femine', target='semine', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ñ', target='non', code='s'),
        Alignment(source=' fuso', target=' fuso', code='n'),
        Alignment(source='', target=',', code='i'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source=':', target='', code='d'),
        Alignment(source=' ', target='', code='d'),
        Alignment(source='gign̾e', target='gignere', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ñ', target='non', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='p̃ualent', target='prevalent', code='s'),
        Alignment(source='. Si ', target='. Si ', code='n'),
        Alignment(source='uͦ', target='vero', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='aliqͥd', target='aliquid', code='s'),
        Alignment(source=' emiserint', target=' emiserint', code='n'),
        Alignment(source='.', target=',', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='unitꝰ', target='unitus', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='sem̃', target='semen', code='s'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='.s.', target='sed', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='aqͦsꝰ', target='aquosus', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='hu.', target='humor', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='un̾', target='unde', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='nullꝰ', target='nullus', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝯceptꝰ', target='conceptus', code='s')
        ]
    # Checking our data isn't wrong before comparing the output
    assert abbr == "".join([alignment.source for alignment in expected])
    assert reg == "".join([alignment.target for alignment in expected])
    assert [alignment.source for alignment in expected if alignment.code == "n"] == [
        alignment.target for alignment in expected if alignment.code == "n"
    ]
    for alignment in expected:
        if alignment.code == "s":
            assert alignment.source != alignment.target
    als = align_words(abbr, reg)
    assert als == expected

def test_shorter_latin():
    abbr = "libus: tribue qs ut non in dignationẽ tuam\nprouocemus elati . sed propitiationis tuȩ capia¬\nmus dona subiecti ꝑ .d.\nConcede nobis misericors ds̃. & studia ꝑuersa de¬\nponere : & scãm semꝑ amare iustitiã. ꝑ¬"
    reg = 'libus, tribue, quaesumus, ut non indignationem tuam provocemus elati, sed propitiationis tuae capiamus dona subjecti. Concede nobis, misericors Deus, et studia perversa deponere, et sanctam semper amare justitiam. '
    expected = [
        Alignment(source='libus', target='libus', code='n'),
        Alignment(source=':', target=',', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='tribue', target='tribue', code='n'),
        Alignment(source='', target=',', code='i'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='qs', target='quaesumus', code='s'),
        Alignment(source='', target=',', code='i'),
        Alignment(source=' ut non ', target=' ut non ', code='n'),
        Alignment(source='in dignationẽ', target='indignationem', code='s'),
        Alignment(source=' tuam ', target=' tuam ', code='n'), # Spaces as new lines or [SPACE] are the same in the alignment
        Alignment(source='prouocemus', target='provocemus', code='s'),
        Alignment(source=' elati', target=' elati', code='n'),
        Alignment(source='', target=',', code='i'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='. ', target='', code='d'), # Deletion grouped together
        Alignment(source='sed propitiationis ', target='sed propitiationis ', code='n'),
        Alignment(source='tuȩ', target='tuae', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='capia¬ mus', target='capiamus', code='s'),
        Alignment(source=' dona ', target=' dona ', code='n'),
        Alignment(source='subiecti', target='subjecti.', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝑ .d. ', target='', code='d'),
        Alignment(source='Concede nobis', target='Concede nobis', code='n'),
        Alignment(source='', target=',', code='i'),
        Alignment(source=' misericors ', target=' misericors ', code='n'),
        Alignment(source='ds̃.', target='Deus,', code='s'),
        Alignment(source=' ', target=' ', code='n'), # Space if they do not change stay
        Alignment(source='&', target='et', code='s'),
        Alignment(source=' studia ', target=' studia ', code='n'), # Space if they do not change stay
        Alignment(source='ꝑuersa', target='perversa', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='de¬ ponere', target='deponere', code='s'),
        Alignment(source='', target=',', code='i'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source=': ', target='', code='d'),
        Alignment(source='&', target='et', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='scãm', target='sanctam', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='semꝑ', target='semper', code='s'),
        Alignment(source=' amare ', target=' amare ', code='n'),
        Alignment(source='iustitiã.', target='justitiam.', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ꝑ¬', target='', code='d')
    ]
    assert abbr.replace("\n", " ") == "".join([alignment.source for alignment in expected])
    assert reg == "".join([alignment.target for alignment in expected])
    assert [alignment.source for alignment in expected if alignment.code == "n"] == [
        alignment.target for alignment in expected if alignment.code == "n"
    ]
    for alignment in expected:
        if alignment.code == "s":
            assert alignment.source != alignment.target
    # Then do real test
    als = align_words(abbr, reg)
    assert als == expected

def test_short_sentence_space_insertion():
    abbr, reg = "ione laloy desiuis.", "ione la loi des iuis"
    expected = [
        Alignment(source='ione la', target='ione la', code='n'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='loy', target='loi', code='s'),
        Alignment(source=' des', target=' des', code='n'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='iuis', target='iuis', code='n'),
        Alignment(source='.', target='', code='d')
    ]
    assert abbr.replace("\n", " ") == "".join([alignment.source for alignment in expected])
    assert reg == "".join([alignment.target for alignment in expected])
    assert [alignment.source for alignment in expected if alignment.code == "n"] == [
        alignment.target for alignment in expected if alignment.code == "n"
    ]
    for alignment in expected:
        if alignment.code == "s":
            assert alignment.source != alignment.target
    als = align_words(abbr, reg)
    assert als == expected

def test_longer_space_insertion_punctuation_deletion():
    abbr = """ione laloy desiuis.:Qins aoroient ⁊ leruoient
les ydoles ⁊si feisoient faire ymages demeintes
camblances ou il auoient lor fiance. """
    reg = """ione la loi des iuis ains aoroient et largioient les ydeles et si fesoient faire ymages de maintes semblances o il auoient lor fiances """
    expected = [
        Alignment(source='ione la', target='ione la', code='n'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='loy', target='loi', code='s'),
        Alignment(source=' des', target=' des', code='n'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='iuis', target='iuis', code='n'),
        Alignment(source='.:', target='', code='d'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='Qins', target='ains', code='s'),
        Alignment(source=' aoroient ', target=' aoroient ', code='n'),
        Alignment(source='⁊', target='et', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='leruoient', target='largioient', code='s'),
        Alignment(source=' les ', target=' les ', code='n'),
        Alignment(source='ydoles', target='ydeles', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='⁊', target='et', code='s'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='si ', target='si ', code='n'),
        Alignment(source='feisoient', target='fesoient', code='s'),
        Alignment(source=' faire ymages de', target=' faire ymages de', code='n'),
        Alignment(source='', target=' ', code='i'),
        Alignment(source='meintes', target='maintes', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='camblances', target='semblances', code='s'),
        Alignment(source=' ', target=' ', code='n'),
        Alignment(source='ou', target='o', code='s'),
        Alignment(source=' il auoient lor ', target=' il auoient lor ', code='n'),
        Alignment(source='fiance', target='fiances', code='s'),
        Alignment(source='.', target='', code='d'),
        Alignment(source=' ', target=' ', code='n')
    ]
    assert abbr.replace("\n", " ") == "".join([alignment.source for alignment in expected])
    assert reg == "".join([alignment.target for alignment in expected])
    assert [alignment.source for alignment in expected if alignment.code == "n"] == [
        alignment.target for alignment in expected if alignment.code == "n"
    ]
    for alignment in expected:
        if alignment.code == "s":
            assert alignment.source != alignment.target
    als = align_words(abbr, reg)
    assert als == expected