#! /usr/bin/python3

"""Execute arbitrary data as a smart contract."""

import struct
import binascii
import logging

from lib import (util, config, exceptions)
from .scriptlib import (utils, blocks, processblock)

FORMAT = '>20sQQQ'
LENGTH = 44
ID = 101

def compose (db, source, contract_id, gasprice, startgas, value, payload_hex):
    if not config.TESTNET:  # TODO
        return

    block = blocks.Block(db, util.last_block(db)['block_hash'])
    code = block.get_code(contract_id)
    payload = binascii.unhexlify(payload_hex)

    if startgas < 0:
        raise processblock.ContractError('negative startgas')
    if gasprice < 0:
        raise processblock.ContractError('negative gasprice')

    # Pack.
    data = struct.pack(config.TXTYPE_FORMAT, ID)
    curr_format = FORMAT + '{}s'.format(len(payload))
    data += struct.pack(curr_format, binascii.unhexlify(contract_id), gasprice, startgas, value, payload)

    return (source, [], data)

class Transaction(object):
    def __init__(self, tx, to, gasprice, startgas, value, data):
        assert type(data) == bytes
        self.block_index = tx['block_index']
        self.tx_hash = tx['tx_hash']
        self.sender = tx['source']
        self.data = data 
        self.to = to
        self.gasprice = gasprice
        self.startgas = startgas
        self.value = value
        self.timestamp = tx['block_time']
    def hex_hash(self):
        return '<None>'
    def to_dict(self):
        dict_ = {
                 'sender': self.sender,
                 'data': utils.hexprint(self.data),
                 'to': self.to,
                 'gasprice': self.gasprice,
                 'startgas': self.startgas,
                 'value': self.value
                }
        return dict_

def parse (db, tx, message):
    if not config.TESTNET:  # TODO
        return

    status = 'valid'
    output, gas_cost, gas_remained = None, None, None

    try:
        # TODO: Use unpack function.
        # Unpack message.
        curr_format = FORMAT + '{}s'.format(len(message) - LENGTH)
        try:
            contract_id, gasprice, startgas, value, payload = struct.unpack(curr_format, message)
            if gasprice > config.MAX_INT or startgas > config.MAX_INT: # TODO: define max for gasprice and startgas
                raise exceptions.UnpackError()
        except (struct.error) as e:
            raise exceptions.UnpackError()

        gas_remained = startgas

        contract_id = util.hexlify(contract_id)
        if contract_id == '0000000000000000000000000000000000000000':
            contract_id = ''

        # ‘Apply transaction’!
        tx_obj = Transaction(tx, contract_id, gasprice, startgas, value, payload)
        block_obj = blocks.Block(db, tx['block_hash'])
        success, output, gas_remained = processblock.apply_transaction(db, tx_obj, block_obj)
        gas_cost = gasprice * (startgas - gas_remained) # different definition from pyethereum’s

    except exceptions.UnpackError as e:
        contract_id, gasprice, startgas, value, payload = None, None, None, None, None
        status = 'invalid: could not unpack'
        output = None
    except processblock.ContractError as e:
        status = 'invalid: no such contract'
        contract_id = None
        output = None
    except processblock.InsufficientStartGas as e:
        have, need = e.args
        logging.debug('Insufficient start gas: have {} and need {}'.format(have, need))
        status = 'invalid: insufficient start gas'
        output = None
    except processblock.InsufficientBalance as e:
        have, need = e.args
        logging.debug('Insufficient balance: have {} and need {}'.format(have, need))
        status = 'invalid: insufficient balance'
        output = None
    except processblock.OutOfGas as e:
        logging.debug('TX OUT_OF_GAS (startgas: {}, gas_remained: {})'.format(startgas, gas_remained))
        status = 'out of gas'
        output = None
    finally:

        if status == 'valid':
            logging.debug('TX FINISHED (gas_remained: {})'.format(gas_remained))

        # Add parsed transaction to message-type–specific table.
        bindings = {
            'tx_index': tx['tx_index'],
            'tx_hash': tx['tx_hash'],
            'block_index': tx['block_index'],
            'source': tx['source'],
            'contract_id': contract_id,
            'gasprice': gasprice,
            'startgas': startgas,
            'gas_cost': gas_cost,
            'gas_remained': gas_remained,
            'value': value,
            'payload': payload,
            'output': output,
            'status': status
        }
        sql='insert into executions values(:tx_index, :tx_hash, :block_index, :source, :contract_id, :gasprice, :startgas, :gas_cost, :gas_remained, :value, :data, :output, :status)'
        cursor = db.cursor()
        cursor.execute(sql, bindings)

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
