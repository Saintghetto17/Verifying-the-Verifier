from vtv.taxonomy import ml_objects, ml_operators, source_operators


def test_single_clause_tags():
    assert ml_operators("Перемешаны изображения") == ["block_permutation"]
    assert ml_operators("удален блок в схеме") == ["element_deletion"]
    assert ml_operators("Изменены подписи к блокам") == ["label_text_edit"]
    assert ml_operators("изменены направления стрелок") == ["edge_rewiring"]
    assert ml_operators("отзеркалено изображение") == ["geometric_distortion"]
    assert ml_operators("Изменены численные значения на изображения") == ["value_fabrication"]
    assert ml_operators("полностью заменено изображение") == ["content_replacement"]
    assert ml_operators("Добавлены блоки") == ["element_addition"]
    assert ml_operators("изменена цветовая палитра") == ["restyling"]
    assert ml_operators("Изменены блоки") == ["generic_edit"]


def test_multi_clause_and_continuation():
    assert ml_operators("Изменен порядок блоков, удалены блоки и подписи к ним") == ["element_deletion", "block_permutation"]
    assert ml_operators("Удалены стрелки, блоки, изменен текст некоторых блоков") == ["label_text_edit", "element_deletion"]


def test_objects_and_source_labels():
    assert ml_objects("Удалены блоки, стрелки, подписи к блокам") == ["blocks", "labels", "arrows"]
    assert source_operators(["labels changed", "colours changed"]) == ["label_text_edit", "restyling"]
    assert source_operators(["something new"]) == ["generic_edit"]
