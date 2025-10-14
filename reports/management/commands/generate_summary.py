from django.core.management.base import BaseCommand, CommandError
from reports.models import StoryTemplate, Story, Graphic, StoryTemplateGraphic, StoryTable, StoryTemplateTable
from reports.services.story_processor import StoryProcessor
from datetime import datetime, date

class Command(BaseCommand):
    help = 'Generate tables and/or graphics for a given story template, story or single graphic'

    def add_arguments(self, parser):
        parser.add_argument('--id', type=int, help='Graphic ID: regenerate a single graphic (requires Graphic model/regenerate logic)')
        parser.add_argument('--story_id', type=int, help='Story ID: regenerate all graphics for this story')
        parser.add_argument('--template_id', type=int, help='StoryTemplate ID: all stories of this template')
        parser.add_argument('--title', action='store_true', help='Process all story templates')
        parser.add_argument('--lead', action='store_true', help='Process all story templates')

    def handle(self, *args, **options):
        template_id = options.get('template_id')
        story_id = options.get('story_id')
        
        if template_id:
            stories = Story.objects.filter(template_id=template_id)
        elif story_id:
            stories = Story.objects.filter(id=story_id)
        else:
            stories = Story.objects.all(active=True)
        total = len(stories) 
        processed, errors = 0,0
        
        for story in stories:
            processor = StoryProcessor(template=None, published_date=None, force_generation=False, story=story)
            if options.get('lead', False): 
                if processor.generate_lead():
                    story.save()
                    self.stdout.write(self.style.SUCCESS(f"Story {story.id} lead generated"))
                else:
                    errors += 1
                    self.stdout.write(self.style.ERROR(f"Story {story.id} lead generation failed"))
            elif options.get('title', False):
                if processor.generate_title():
                    story.save()
                    self.stdout.write(self.style.SUCCESS(f"Story {story.id} title generated"))
                else:
                    errors += 1
                    self.stdout.write(self.style.ERROR(f"Story {story.id} title generation failed"))
            else:
                if processor.generate_lead() and processor.generate_title():
                    story.save()
                    self.stdout.write(self.style.SUCCESS(f"Story {story.id} title and lead generated"))
            processed += 1
        

        self.stdout.write(self.style.SUCCESS(f"Done. processed={processed}/{total} errors={errors}"))