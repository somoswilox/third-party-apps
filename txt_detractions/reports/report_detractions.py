class ReportInvBalTxt(object):

    def __init__(self, obj, line, data):
        self.obj = obj
        self.line = line
        self.data = data

    def get_content(self):
        raw = ''
        spaces = '                                   '
        total_1, total_2 = str(self.line['total_amount']).split('.')
        raw += '{caracter}{ruc}{name}{lot_number}{total_1}{total_2}\r\n'.format(
            caracter=self.line['01'],
            ruc=self.line['ruc'],
            name=self.line['name'].ljust(35) if len(self.line['name']) < 35 else self.line['name'][:35],
            lot_number=self.line['lot_number'],
            total_1=total_1.zfill(13),
            total_2=total_2.zfill(2),
        )

        template = '6{ruc}{spaces}000000000{selection_ids}{bank}{amount_1}{amount_2}{operation_type}{dateAA}{datemm}{code}{ref_1}{ref_2}\r\n'
        for value in self.data:
            amount_1, amount_2 = value['amount'].split('.')
            ref = value['ref'] or ''
            if len(ref) > 1 and ref[1] == ' ':
                ref = ref[2:]
            if '-' in ref:
                parts = ref.split('-', 1)
                ref_1 = parts[0][:4].ljust(4)
                ref_2 = parts[1].replace('-', '').zfill(8)[-8:]
            else:
                ref_1 = ref[:4].ljust(4)
                ref_2 = ref[-8:].zfill(8) if ref else '00000000'
            raw += template.format(
                ruc=value['ruc'],
                spaces=spaces,
                selection_ids=value['selection_ids'],
                bank=value['bank'],
                amount_1=amount_1.zfill(13),
                amount_2=amount_2.zfill(2),
                operation_type=value['operation_type'],
                dateAA=value['invoice_date'].strftime('%Y'),
                datemm=value['invoice_date'].strftime('%m'),
                code=value['document_type'],
                ref_1=ref_1,
                ref_2=ref_2,
            )
        return raw

    def get_filename(self):
        return 'D{vat}{lot}.txt'.format(
            lot=self.obj['lot_number'],
            vat=self.obj['vat']
        )
