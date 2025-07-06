# ETL Migration Strategy

## Overview
This document outlines the migration from standalone ETL processes to Django-integrated services.

## What's Been Created

### 1. Service Layer Structure
- `reports/services/base.py` - Base service class with common functionality
- `reports/services/dataset_sync.py` - Dataset synchronization service
- `reports/services/story_generation.py` - Story generation service
- `reports/services/email_service.py` - Email delivery service

### 2. Management Commands
- `synch_data.py` - Updated to use DatasetSyncService
- `generate_stories.py` - New command for story generation
- `send_stories.py` - New command for email sending
- `run_etl_pipeline.py` - Unified command for the entire pipeline

## Migration Steps

### Phase 1: Service Implementation (Current)
✅ Created service architecture
✅ Updated management commands
⏳ **Next:** Implement actual business logic

### Phase 2: Business Logic Migration
You need to port the logic from your existing files:

1. **Dataset Synchronization** (`daily_tasks/synch_datasets.py` → `reports/services/dataset_sync.py`)
   - Move the `Dataset` class logic into `DatasetProcessor.synchronize()`
   - Update to use Django ORM instead of raw SQL
   - Port all synchronization logic

2. **Story Generation** (`daily_tasks/make_data_insights.py` → `reports/services/story_generation.py`)
   - Move the `Story` class logic into `StoryProcessor.generate()`
   - Update to use Django ORM
   - Port AI generation logic

3. **Email Sending** (`daily_tasks/send_data_insights.py` → `reports/services/email_service.py`)
   - Port email sending logic
   - Update to use Django email settings

### Phase 3: Configuration Migration
- Update Django settings to include all necessary ETL configurations
- Remove dependencies on `decouple` if using Django settings
- Update database connection handling

### Phase 4: Testing & Validation
- Test each service individually
- Test the complete pipeline
- Validate data integrity
- Performance testing

## Key Benefits of This Migration

1. **Consistency**: All services use the same logging, configuration, and error handling
2. **Maintainability**: Code is organized in logical services
3. **Flexibility**: Can still run individual steps or the complete pipeline
4. **Django Integration**: Full access to ORM, admin, and other Django features
5. **Transaction Management**: Proper database transaction handling

## Running the New Commands

```bash
# Sync datasets only
python manage.py synch_data

# Sync specific dataset
python manage.py synch_data --id 1

# Generate stories
python manage.py generate_stories

# Generate stories for specific date
python manage.py generate_stories --date 2025-01-01

# Send emails
python manage.py send_stories

# Run complete pipeline
python manage.py run_etl_pipeline

# Run pipeline with options
python manage.py run_etl_pipeline --date 2025-01-01 --force
```

## Next Steps

1. **Implement Business Logic**: Port the actual ETL logic from your existing files
2. **Create Data Models**: Add any missing Django models for stories, logs, etc.
3. **Update Settings**: Configure Django settings for ETL operations
4. **Add Tests**: Create unit tests for the services
5. **Documentation**: Document the new ETL processes

## Keeping Flexibility

If you still want to run processes independently:
- The services can be imported and used in standalone scripts
- Management commands can be called programmatically
- You can create a lightweight Django app just for ETL if needed

This approach gives you the best of both worlds: Django integration when you want it, and the ability to run standalone when needed.
