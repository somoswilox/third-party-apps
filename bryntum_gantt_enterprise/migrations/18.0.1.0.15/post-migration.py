def migrate(cr, version):
    """
    Fix NULL values in project_task boolean fields
    before the CHECK constraint is applied.
    """
    cr.execute(
        """
        UPDATE project_task
        SET force_manual = false
        WHERE force_manual IS NULL
    """
    )

    cr.execute(
        """
        UPDATE project_task
        SET force_auto = false
        WHERE force_auto IS NULL
    """
    )
