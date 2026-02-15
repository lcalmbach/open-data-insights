from django.core.management.base import BaseCommand, CommandError
from reports.models.story_template import StoryTemplate
from reports.models.story import Story
from reports.models.graphic import Graphic
from reports.models.graphic import StoryTemplateGraphic
from reports.models.story_table import StoryTable
from reports.models.story_table_template import StoryTemplateTable
from reports.services.story_processor import StoryProcessor
from datetime import datetime, date

class Command(BaseCommand):
    help = 'Generate tables and/or graphics for a given story template, story or single graphic'

    def add_arguments(self, parser):
        parser.add_argument('--id', type=int, help='Graphic ID: regenerate a single graphic (requires Graphic model/regenerate logic)')
        parser.add_argument('--graphic_template_id', type=int, help='Graphic template ID: regenerate a all graphics done from the same graphic-template')
        parser.add_argument('--table_template_id', type=int, help='Table template ID: regenerate a all tables done from the same table-template')
        parser.add_argument('--story_id', type=int, help='Story ID: regenerate all graphics for this story')
        parser.add_argument('--story_template_id', type=int, help='StoryTemplate ID: all stories of this template')
        parser.add_argument('--tables', action='store_true', help='Generate tables')
        parser.add_argument('--graphics', action='store_true', help='Generate graphics')
        parser.add_argument('--stories', action='store_true', help='Regenerate stories')
        parser.add_argument('--all', action='store_true', help='Process all story templates')

    def handle(self, *args, **options):
        story_template_id = options.get('story_template_id')
        story_id = options.get('story_id')
        graphic_template_id = options.get('graphic_template_id')
        table_template_id = options.get('table_template_id')
        id = options.get('id')
        all_flag = options.get('all', False)
        graphics_flag = options.get('graphics', False)
        tables_flag = options.get('tables', False)
        stories_flag = options.get('stories', False)
        
        if not options.get('tables') and not options.get('graphics') and not options.get('stories'):
            self.stdout.write(self.style.WARNING("No action specified. Use --tables, --graphics, and/or --stories."))
            return

        # Validate mutually exclusive selection: only one of template_id / story_id / id / all
        selection_flags = sum(bool(x) for x in (story_template_id, story_id, id, graphic_template_id, table_template_id, all_flag))
        if selection_flags == 0:
            raise CommandError("Provide one of --template_id, --story_id, --id or --all to select what to process.")
        if selection_flags > 1:
            raise CommandError("Provide only one of --template_id, --story_id, --id (graphic) or --all (not multiple).")

        # Handle single graphic id (best-effort; requires a Graphic model / regenerate API)
        graphics = []
        tables = []
        stories = []
        if id and graphics_flag:
            graphics = [Graphic.objects.get(id=id)]
            template = graphics[0].story.template
        elif id and tables_flag:
            tables = [StoryTable.objects.get(id=id)]
            template = tables[0].story.template
        elif graphic_template_id:
            template = StoryTemplateGraphic.objects.get(id=graphic_template_id)
            graphics = template.story_template_graphics.all()
        elif table_template_id:
            template = StoryTemplateTable.objects.get(id=table_template_id)
            tables = template.story_template_tables.all()
        elif story_id:
            graphics = Graphic.objects.filter(story_id=story_id)
            tables = StoryTable.objects.filter(story_id=story_id)
            stories = Story.objects.filter(id=story_id)
        elif story_template_id:
            template = StoryTemplate.objects.get(id=story_template_id)
            graphics = Graphic.objects.filter(story__templatefocus__story_template=template)
            tables = StoryTable.objects.filter(story__templatefocus__story_template=template)
            stories = Story.objects.filter(templatefocus__story_template=template)
        elif all_flag:
            if graphics_flag:
                graphics = Graphic.objects.all()
            if tables_flag:
                tables = StoryTable.objects.all()
            if stories_flag:
                stories = Story.objects.all()

        total, processed, errors = 0,0,0
        if options.get('graphics'):
            total = len(graphics)
        if options.get('tables'):
            total += len(tables)
        if options.get('stories'):
            total += len(stories)
        
        
        if options.get('graphics'):
            for graphic in graphics:
                processor = StoryProcessor(anchor_date=None, template=None, force_generation=False, story=graphic.story)
                if not processor.generate_graphic(graphic):
                    errors += 1
                processed += 1
        if options.get('tables'):            
            for table in tables:
                processor = StoryProcessor(anchor_date=None, template=None, force_generation=False, story=table.story)
                if not processor.generate_table(table):
                    errors += 1
                processed += 1
        if options.get('stories'):
            for story in stories:
                processor = StoryProcessor(anchor_date=None, template=None, force_generation=True, story=story)
                if not processor.generate_story():
                    errors += 1
                processed += 1

        self.stdout.write(self.style.SUCCESS(f"Done. processed={processed}/{total} errors={errors}"))
