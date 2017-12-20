alter table instruments rename to instrument;
alter table positions rename to position;
alter table pvtypes rename to pvtype;
alter table pvs rename to pv;

alter sequence instruments_id_seq rename to instrument_id_seq;
alter sequence pvtypes_id_seq rename to pvtype_id_seq;
alter sequence pvs_id_seq rename to pv_id_seq;
alter sequence positions_id_seq rename to position_id_seq;

alter table position_pv rename column positions_id to position_id;
alter table position_pv rename column pvs_id to pv_id;

alter table position rename column instruments_id to instrument_id;

alter table instrument_pv rename column instruments_id to instrument_id;
alter table instrument_pv rename column pv_id to pv_id;
alter table instrument_pv rename column pvs_id to pv_id;

alter table pv rename column pvtypes_id to pvtype_id;


update info set value=2.0 where keyname='version';


alter table slewscanpositioners  add column config_id INTEGER;
alter table slewscanpositioners  add constraint slewscanpositions_config_id_fkey foreign key (config_id) references config(id);

update slewscanpositioners set config_id=13;

insert into info (keyname, value) values ('epics_scandata_prefix', '13XRM:ScanData:');
