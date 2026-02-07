from app.alignment import token_splitter, Alignment, reprocess_space


def test_token_splitter():
    """Ensure token splitter works correctly."""
    assert token_splitter(
        "ceci est un .xxv. d'or n'est-ce pas.Mais est-ce que ça marche ? .s."
    ) == ['ceci', ' ', 'est', ' ', 'un', ' ', '.xxv.', ' ', "d'or", ' ', "n'est-", 'ce', ' ', 'pas.', 'Mais', ' ',
          'est-', 'ce', ' ', 'que', ' ', 'ça', ' ', 'marche', ' ', '?', ' ', '.s.']
    assert token_splitter(" oĩa\uf1ac m̃b ͣ corꝑriᷤᷤ") == [' ', 'oĩa\uf1ac', ' ', 'm̃b ͣ', ' ', 'corꝑriᷤᷤ']
    assert token_splitter("ortꝰ.⁊ sp̃s. ") == ['ortꝰ.', '⁊', ' ', 'sp̃s.', ' ']


def test_reprocessing_space():
    # abbr = """REATOR UOENS animaliũ gꝰ firmit̾ ꝑman̾e ⁊ ñ ꝑire : ꝑ coitũ illiꝰ gen̾atio̾ẽ disposuit renouari. ut renouatũ ĩt̾itũ ex toto ñ haberet. Ideoq c̾plasmauit ai̾alibꝰ m̃bra natͣlia q̃ ad ħ opꝰ apta forent ⁊ ꝓͥa. eiꝰq tã mirabilẽ delectatio̾ẽ ĩseruit u̇ nullũ sit ai̾al qd ñ ꝑ coitũ nimiũ delectet᷑. Nã si ai̾alia coitũ odirent: ai̾aliũ genꝰ ꝓ c̾co ꝑiret. In tantũ .N. nat᷑alr̾ ĩẽ. coitꝰ. u̇ ꝑ multa tẽporͣ ĩpeditꝰ ẽ expellendi possi bilitaᷤᷤ adfu̾it oĩ pene ro̾e pꝰposita. fiat coitꝰ ꝑ duo ai̾alia. ꝑ unũ .N. sem̃ emitit᷑. cui aliud obuiando ĩ sua ꝓfundiͣtate ꝯcauitate : illud recip̃ un̾diq ne ex aliqͣ parte possit diffundi.⁊ disꝑgi. Ria s̃ in coitu. Appetitꝰ ex cogitatiõe fantastica ortꝰ.⁊ sp̃s. ⁊ hũor. Ap petitꝰ ab epate. sp̃s a corde. Hũor a c̾ebro. Nã cũ delectabit sp̃s motꝰ sit ĩ coitu ꝑ motũ. oĩa m̃b ͣ corꝑriᷤᷤ ꝯuͣeltᷤᷤcunt ⁊ ꝑ calorẽ eliqͣt᷑ hũor qͥ ẽ.ĩ ce̾b ͦ ⁊ eliqͣtꝰ attͣhit᷑ ꝑ uenaᷤᷤ q̃ pꝰ aureᷤᷤ ducunt᷑ ad testiculoᷤᷤ. ⁊ in̾ ꝑ uͥga ĩ uuluã eicit᷑. Nã u̇ ypoc̾s dic̃ qͥbꝰc̾q uene q̃ pꝰ aureᷤᷤ ducunt᷑ excuse fu̾int femine ñ fuso : gign̾e ñ p̃ualent. Si uͦ aliqͥd emiserint. unitꝰ sem̃.s. aqͦsꝰ hu. un̾ nullꝰ ꝯceptꝰ f̾i potest. Et qm̃ alii uͥga tendunt ⁊ minꝰ coeunteᷤᷤ : sem̃ emit̾e ñ ualent. ⁊ alii s̃ qͥ sem̃ emmitunt ⁊ ñ uolenteᷤᷤ. ⁊ uirgã ñ ĩtendunt. Et alii s̃ qͥ nec appetunt nec uirgã erigunt : nec sem̃ emitunt. Ꝙalit̃ gͦ ista fuint. nob̾ ẽ. declarandũ. Cũ gͥ orit᷑ appetitꝰ ĩ epate ut dict̾ ẽ. mouet᷑ sp̃s a corde qͥ ꝑ arteriaᷤᷤ descendenᷤᷤ ad uirgã : ꝯcauũ uirge n̾uũ re plet ⁊ replendo ĩ duraᷤᷤ rigiditateᷤᷤ ĩtenduͥnt. S sem̃ emit̾e ñ ualet : dũ seminał humiditatiᷤᷤ fu̾it ĩdigẽtia ac deffectꝰ ĩ c̾eb ͦ.Cũ uͦ hu̾nda i̾nt ħ hui̾taᷤᷤ ĩ c̾eb ͦ. ⁊ fui̾t ĩdigentia ac defectꝰ uentositatiᷤᷤ ĩ corde : sem̃ emitit᷑ ⁊̃ a nolentibꝰ s uͥga ñ ĩtendit᷑. Cũ uͦ hoꝵ utroꝵq fit ĩdigentia : nec uirgͣ ualet ĩtendi nec sem̃ emiti.Illi uͦ qͥ ħ tria integͣ hu̾int : coeuntes ad gen̾atio̾ẽ ꝑfic̾e p̃ualent.⁊. deducit᷑ eiᷤᷤ sem̃ ac̾eb ͦ. ꝑ uenaᷤᷤ q̃ pꝰ aureᷤᷤ descendunt.⁊ ꝑ eas ĩ spinalẽ medullã emitit᷑. ⁊ a medulla ĩ reneᷤᷤ.⁊ a renibꝰ in didimoᷤᷤ.⁊ a didimiᷤᷤ ꝑ uirgã emititur ñ ꝑ urinalẽ uiã : s ꝑ aliis seminiᷤᷤ ꝓpriã His itaq sic p̃libatiᷤᷤ. dicendũ ẽ. qͥd sit sem̃.⁊ quomͦ illud diffinierit gał. Dic̃ enĩ. Sem̃ ẽ. sub̾a hum̾da ⁊ purͣ ⁊ calida un̾ fit homo.Iter̾ sem̃ ẽ. sp̃s caliduᷤᷤ currenᷤᷤ ⁊ spirando ĩpellenᷤᷤ hui̾da corꝑiᷤᷤ. effectũ similẽ facienᷤᷤ. illi uñ ꝓcessit. It̾ gał. ĩ lib ͦ de cura m̃broꝵ. Sem̃ ẽ. sp̃s ⁊ humor spumosꝰ. Spumosꝰ aũ fit humor ꝑ motũ sic̃ ẽ. uid̾e ĩ tẽpestate mariᷤᷤ. Declarat᷑ aũ ita. Postqͣ sem̃ eicit᷑ : copiosũ apparet. Pꝰ modicũ : nimiᷤᷤ diminuit᷑.⁊ ñ re manet ĩtegr̾. ut sputũ aut mucꝰ. qr ħ s̃ liqͥda ⁊ cruda. Sem̃ aũ ẽ densũ ⁊ coctũ. Qd̾ cũ cecidit ĩ locũ ñ ꝓpͥũ plen̾  uitali spũ format᷑. ĩ 10"""
    # reg = """reator volens animalium genus firmiter permanere et non perire, per coitum illius generacionem disposuit renovari, ut renovatum interitum ex toto non haberet. Ideoque complasmavit animalibus membra naturalia quod ad hoc opus apta forent et propria, eiusque tam mirabilem delectacionem inseruit ut nullum sit animalium quod non per coitum nimium delectetur. Nam si animalia coitum odirent, animalium genus pro certo periret. In tantum enim naturaliter inest coitus. ut per multa tempora impeditus, cum expellendi possibilitas affuerit, omni pene racione postposita. fiat coitus per duo animalia, per unum enim semen emittitur, cui aliud obviando in sua profunditate concavitate illud recipit undique ne ex aliqua parte possit diffundi. et dispergi. Tria sunt in coitu: appetitus ex cogitacione fantastica ortus, et spiritus et humor. Appetitus ab epate, spiritus a corde, humor a cerebro; nam cum delectabilitur spiritus motus sit in coitu, per motum omnia membra corporis convalescunt et per calorem eliquatur humor qui est in cerebro, et eliquatus attrahitur per venas que post aures ducuntur ad testiculos, et inde per virgam in vulvam eicitur. Nam ut Ypocras dicit: quibuscumque vene que post aures ducuntur excise fuerint, semine non fuso, gignere non prevalent. Si vero aliquid emiserint, unitus semen sed aquosus humor unde nullus conceptus fieri potest. Et quoniam alii virgam tendunt et minus coeuntes semen emittere non valent, et alii sunt qui semen emittunt et non volentes. et virgam non intendunt. et alii sunt qui nec appetunt, nec virgam erigunt, nec semen emittunt, qualiter [[[]]] ista fiant. nobis est declarandum. Cum igitur oritur appetitus in epate, ut dictum est, movetur spiritus a corde, qui per arterias descendens ad virgam, concavum virge nervum replet et replendo in duras rigiditates intendirunt. Sed semen emittere non vale : dum seminalis humiditatis fuerit indigencia ac defectus in cerebro. Cum vero habundaverint hec humiditas in cerebro et fuerit indigencia et defectus ventositatis in corde, semen emittitur etiam a nolentibus. sed virga non tenditur. Cum vero horum utrorumque fit indigencia: nec virga valet intendi, nec semen emitti. Illi vero qui hec tria integra habuerint coeuntes ad generacionem proficere prevalent et deducitur eis semen a cerebro per venasque post aures descendunt, et per eas in spinalem medullam emittitur et a medulla in renes, et a renibus ad didimos, et a didimis per virgam emittitur, non per urinalem viam, sed per aliis seminis propria. Hiis itaque sic prelibatis, dicendum est quid sit semen et quomodo illud diffinierit Galenus. Dicit enim: semen est substancia humida et pura et calida, unde fit homo. Iterum: semen est spiritus calidus currens et spirando impellens humida corporis, effectum similem faciens. illi unde processit. Item Galenus in libro de cura membrorum: semen est spiritus et humor spumosus. Spumosus autem fit humor per motum, sicut est videre in tempestate maris. Declaratur autem ita. postquam semen eicitur, copiosum apparet. post modicum nimis diminuitur. et non remanet integrum, ut sputum aut mucus, quia hec sunt liquida et cruda. semen autem est densum et coctum. Quod cum cecidit in locum non proprium plenumque vitali spiritu formatur. in 10"""
    #
    # als, s1, s2 = align_words(abbr, reg)

    exemple1 = [Alignment('expellendi', 'expellendi', 'n'), Alignment(' ', ' ', 'n'),
                Alignment('possi', 'possibilitas', 's'), Alignment(' ', ' ', 'n'), Alignment('bilitaᷤᷤ', None, 'd'),
                Alignment(' ', None, 'd'), Alignment('adfu̾it', 'affuerit', 's'), Alignment(' ', ', ', 's'),
                Alignment('oĩ', 'omni', 's'), Alignment(' ', ' ', 'n'), Alignment('pene', 'pene', 'n'),
                Alignment(' ', ' ', 'n'), Alignment('ro̾e', 'racione', 's'), Alignment(' ', ' ', 'n'),
                Alignment('pꝰposita.', 'postposita.', 's'), ]

    exemple2 = [Alignment(source='ortꝰ.', target='ortus,', code='s'), Alignment(source=None, target=' ', code='i'),
                Alignment(source='⁊', target='et', code='s'), Alignment(source=' ', target=' ', code='n'),
                Alignment(source='sp̃s.', target='spiritus', code='s'), Alignment(source=' ', target=' ', code='n'),
                Alignment(source='⁊', target='et', code='s'), Alignment(source=' ', target=' ', code='n'),
                Alignment(source='hũor.', target='humor.', code='s'), Alignment(source=' ', target=' ', code='n'),
                Alignment(source='Ap', target=None, code='d'), Alignment(source=' ', target=None, code='d'),
                Alignment(source='petitꝰ', target='Appetitus', code='s'), Alignment(source=' ', target=' ', code='n'),
                Alignment(source='ab', target='ab', code='n'), Alignment(source=' ', target=' ', code='n'),
                Alignment(source='epate.', target='epate,', code='s')]

    assert reprocess_space(
        [Alignment(source='expellendi', target='expellendi', code='n'), Alignment(source=' ', target=' ', code='n'),
         Alignment(source='possi', target='possibilitas', code='s'), Alignment(source=' ', target=' ', code='n'),
         Alignment(source='bilitaᷤᷤ', target=None, code='d'), Alignment(source=' ', target=None, code='d'),
         Alignment(source='adfu̾it', target='affuerit', code='s'), Alignment(source=' ', target=', ', code='s'),
         Alignment(source='oĩ', target='omni', code='s'), Alignment(source=' ', target=' ', code='n'),
         Alignment(source='pene', target='pene', code='n'), Alignment(source=' ', target=' ', code='n'),
         Alignment(source='ro̾e', target='racione', code='s'), Alignment(source=' ', target=' ', code='n'),
         Alignment(source='pꝰposita.', target='postposita.', code='s')]) == [
        Alignment(source='expellendi', target='expellendi', code='n'), Alignment(source=' ', target=' ', code='n'),
        Alignment(source='possi bilitaᷤᷤ', target='possibilitas', code='s'),
        Alignment(source=' ', target=' ', code='n'), Alignment(source='adfu̾it', target='affuerit', code='s'),
        Alignment(source=' ', target=', ', code='s'), Alignment(source='oĩ', target='omni', code='s'),
        Alignment(source=' ', target=' ', code='n'), Alignment(source='pene', target='pene', code='n'),
        Alignment(source=' ', target=' ', code='n'), Alignment(source='ro̾e', target='racione', code='s'),
        Alignment(source=' ', target=' ', code='n'), Alignment(source='pꝰposita.', target='postposita.', code='s')]

