"""Use the language named by an abstract heading throughout that section."""


def apply_abstract_languages(document):
    section_language = None
    for block in document.logical_blocks:
        if block.type == 'heading':
            title = ' '.join(block.content.split()).strip(' .:').casefold()
            section_language = {'abstract': 'en', 'streszczenie': 'pl'}.get(title)
        if section_language:
            # Formatting checks use block.language; grammar uses Block_context.
            block.language = section_language
            block.section_language = section_language
