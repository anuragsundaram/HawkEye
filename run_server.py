#!/usr/bin/env python3
"""
Hawkeye - Database Monitoring Dashboard - Server Startup Script
Modern Database Monitoring Application
"""

import os
import sys
import logging
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.absolute()
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Start the Hawkeye - Database Monitoring Dashboard server"""
    
    try:
        # Import Flask app
        from app import app
        
        logger.info("=" * 70)
        logger.info("Hawkeye - Database Monitoring Dashboard - Server Starting")
        logger.info("=" * 70)
        
        # Get configuration
        host = app.config.get('HOST', '127.0.0.1')
        port = app.config.get('PORT', 5000)
        debug = app.config.get('DEBUG', False)
        
        logger.info(f"Server configuration:")
        logger.info(f"  Host: {host}")
        logger.info(f"  Port: {port}")
        logger.info(f"  Debug Mode: {debug}")
        logger.info(f"  Flask Version: {app.import_name}")
        
        # Check if configuration is complete
        if not app.config.get('TARGETS'):
            logger.warning("WARNING: No database targets configured!")
            logger.warning("Please configure TARGETS in config.py before running in production.")
        
        if not app.config.get('USERS'):
            logger.warning("WARNING: No users configured!")
            logger.warning("Please configure USERS in config.py before running in production.")
        
        logger.info("-" * 70)
        logger.info(f"Starting server at http://{host}:{port}")
        logger.info("Press CTRL+C to stop the server")
        logger.info("-" * 70)
        
        # Start the Flask development server
        # For production, use a proper WSGI server like Gunicorn:
        # gunicorn -w 4 -b 0.0.0.0:5000 'hawkeye:app'
        app.run(
            host=host,
            port=port,
            debug=debug,
            use_reloader=debug,
            threaded=True
        )
        
    except ImportError as e:
        logger.error(f"Failed to import hawkeye module: {e}")
        logger.error("Make sure all dependencies are installed: pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Server startup failed: {e}")
        logger.error("Check your configuration and try again.")
        sys.exit(1)


if __name__ == '__main__':
    main()
