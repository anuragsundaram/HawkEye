menu_tree = {'get_target': ['target'
                              , ['get_top_activity'
                                 , 'get_tuning_advisor'
                                 , 'get_sql_monitor'
                                 , 'get_session_monitor'
                                 , 'get_rman_status'
                                 , 'get_dml_locks']]
             , 'get_target_snapshot': ['target'
                                       , ['get_awr_report'
                                          , 'get_ash_report'
                                          , 'get_advisor_tasks'
                                          , 'get_advisor_findings']]
            
             , 'get_query': ['query'
                             , ['get_query_text'
                                , 'get_query_plan'
                                , 'get_query_waits'
                                , 'get_query_long_ops'
                                , 'get_query_plan_stats'
                                , 'get_query_report']]
             , 'get_session': ['sid'
                               , ['get_session_stats']]
             , 'get_table': ['table'
                             , ['get_table_columns'
                                , 'get_table_indexes'
                                , 'get_table_partitions'
                                , 'get_table_ddl'
                                , 'get_row_count'
                                , 'get_insert_from_select'
                                , 'get_scan_speed']]
             , 'get_view': ['view'
                            , ['get_view_columns'
                               , 'get_view_text']]
            , 'get_app': ['user'
                              , ['get_targets_admin', 'get_users_admin']]
             , 'logout': ['user', []]}
